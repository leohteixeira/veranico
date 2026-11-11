"""The quote aggregate: every transition of SPEC section 6 is decided here, with no I/O.

Each operation returns a `Mutation`: the new quote, the audit entries to append and the
outbox records to write. Identifiers and timestamps are arguments, never generated inside,
so an operation can run again on a retried transaction and give the same answer.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from veranico.modules.pricing.contracts import CoverDefinition, PricedCover
from veranico.modules.quoting.contracts import (
    Actor,
    AuditEntry,
    Decision,
    DeliveryAttempt,
    DeliveryState,
    QuoteLocation,
    QuoteStatus,
    QuoteView,
    Submission,
    SubmissionApproved,
    SubmissionPayload,
)
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import InvalidArgumentsError, InvalidStateError
from veranico.shared.kernel.ids import DatasetId, EventId, QuoteId, SubmissionId, WorkspaceId

MAX_NOTE_CHARS = 500
DeliveryStatus = Literal["not_started", "delivering", "delivered", "abandoned"]

_NOT_STARTED = DeliveryState(
    status="not_started", attempts=0, receipt_id=None, last_error_code=None
)


@dataclass(frozen=True, slots=True)
class Mutation:
    """What one operation changes, written by the repository as a unit."""

    quote: "Quote"
    audit: tuple[AuditEntry, ...] = ()
    outbox: tuple[OutboxRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class Quote:
    quote_id: QuoteId
    workspace_id: WorkspaceId
    created_at: datetime
    status: QuoteStatus
    location: QuoteLocation
    dataset_id: DatasetId
    cover: CoverDefinition
    priced: PricedCover
    submission: Submission | None = None
    current_event_id: EventId | None = None
    idempotency_ref: str | None = None

    @classmethod
    def draft(
        cls,
        *,
        quote_id: QuoteId,
        workspace_id: WorkspaceId,
        created_at: datetime,
        location: QuoteLocation,
        dataset_id: DatasetId,
        cover: CoverDefinition,
        priced: PricedCover,
        actor: Actor,
        key_id: str | None = None,
        idempotency_ref: str | None = None,
    ) -> Mutation:
        quote = cls(
            quote_id=quote_id,
            workspace_id=workspace_id,
            created_at=created_at,
            status="draft",
            location=location,
            dataset_id=dataset_id,
            cover=cover,
            priced=priced,
            idempotency_ref=idempotency_ref,
        )
        return Mutation(quote, (_entry(created_at, actor, "quote_created", _key(key_id)),))

    def view(self, audit: list[AuditEntry]) -> QuoteView:
        return QuoteView(
            quote_id=self.quote_id,
            workspace_id=self.workspace_id,
            created_at=self.created_at,
            status=self.status,
            location=self.location,
            dataset_id=self.dataset_id,
            cover=self.cover,
            priced=self.priced,
            submission=self.submission,
            audit=audit,
        )

    def request_submission(
        self,
        *,
        submission_id: SubmissionId,
        carrier_id: str,
        actor: Actor,
        at: datetime,
        key_id: str | None = None,
    ) -> Mutation:
        """Idempotent per quote: a quote with a submission is returned unchanged."""
        if self.submission is not None:
            return Mutation(self)
        if self.status != "draft":
            raise InvalidStateError("a submission can be requested only for a draft quote")
        submission = Submission(
            submission_id=submission_id,
            carrier_id=carrier_id,
            requested_at=at,
            decided_at=None,
            decision_note=None,
            delivery=_NOT_STARTED,
        )
        params: dict[str, str | int | float] = {"carrier_id": carrier_id, **_key(key_id)}
        return Mutation(
            replace(self, status="pending_approval", submission=submission),
            (_entry(at, actor, "submission_requested", params),),
        )

    def decide(self, decision: Decision, *, event_id: EventId, at: datetime) -> Mutation:
        """Approve or reject a pending approval; an approval also yields the outbox record."""
        if self.status != "pending_approval" or self.submission is None:
            raise InvalidStateError("the approval is not pending")
        if decision.note is not None and len(decision.note) > MAX_NOTE_CHARS:
            raise InvalidArgumentsError(f"the note has more than {MAX_NOTE_CHARS} characters")
        if not decision.approve:
            rejected = self._with_submission(
                "rejected", self.submission.delivery, decided_at=at, note=decision.note
            )
            return Mutation(rejected, (_entry(at, "human", "rejected", note=decision.note),))
        approved = replace(
            self._with_submission(
                "approved",
                _delivery(self.submission, "delivering"),
                decided_at=at,
                note=decision.note,
            ),
            current_event_id=event_id,
        )
        event = SubmissionApproved(
            event_id=event_id,
            occurred_at=at,
            workspace_id=self.workspace_id,
            carrier_id=self.submission.carrier_id,
            data=SubmissionPayload(
                quote_id=self.quote_id,
                submission_id=self.submission.submission_id,
                location=self.location,
                cover=self.cover,
                premium=self.priced.premium.premium,
                rate_on_line=self.priced.premium.rate_on_line,
            ),
        )
        record = OutboxRecord(event=event, quote_id=self.quote_id, status="pending", created_at=at)
        return Mutation(approved, (_entry(at, "human", "approved", note=decision.note),), (record,))

    def record_attempt(
        self, record: OutboxRecord, attempt: DeliveryAttempt, *, at: datetime
    ) -> Mutation:
        """Record one webhook attempt, once per attempt number; a receipt submits the quote.

        Late calls never regress state: after the receipt, a further attempt only adds its
        audit entry; after an abandonment, a receipt still submits the quote.
        """
        submission = self._delivering_submission(record)
        if attempt.attempt in record.recorded_attempts:
            return Mutation(self)
        recorded = replace(
            record,
            recorded_attempts=(*record.recorded_attempts, attempt.attempt),
            last_attempt_at=at,
        )
        params: dict[str, str | int | float] = {
            "attempt": attempt.attempt,
            "duration_ms": attempt.duration_ms,
        }
        if attempt.status_code is not None:
            params["status_code"] = attempt.status_code
        if attempt.error_code is not None:
            params["error_code"] = attempt.error_code
        attempted = _entry(at, "system", "webhook_attempt", params)
        if submission.delivery.status == "delivered":
            return Mutation(self, (attempted,), (recorded,))
        attempts = len(recorded.recorded_attempts)
        if attempt.receipt_id is None:
            delivery = DeliveryState(
                status=submission.delivery.status,
                attempts=attempts,
                receipt_id=None,
                last_error_code=attempt.error_code,
            )
            return Mutation(
                replace(self, submission=_with_delivery(submission, delivery)),
                (attempted,),
                (recorded,),
            )
        delivery = DeliveryState(
            status="delivered",
            attempts=attempts,
            receipt_id=attempt.receipt_id,
            last_error_code=None,
        )
        return Mutation(
            replace(self, status="submitted", submission=_with_delivery(submission, delivery)),
            (
                attempted,
                _entry(at, "carrier", "receipt_recorded", {"receipt_id": attempt.receipt_id}),
            ),
            (replace(recorded, status="delivered"),),
        )

    def mark_abandoned(self, record: OutboxRecord, *, at: datetime) -> Mutation:
        """Give the delivery up; a no-op once it is delivered or already abandoned."""
        submission = self._delivering_submission(record)
        if record.terminal:
            return Mutation(self)
        return Mutation(
            replace(
                self, submission=_with_delivery(submission, _delivery(submission, "abandoned"))
            ),
            (
                _entry(
                    at, "system", "delivery_abandoned", {"attempts": submission.delivery.attempts}
                ),
            ),
            (replace(record, status="abandoned"),),
        )

    def request_redelivery(self, record: OutboxRecord, *, actor: Actor, at: datetime) -> Mutation:
        """Start a new delivery round of the same event, only after an abandonment.

        The event id is kept (the carrier deduplicates by it); attempt numbers continue
        after the highest one recorded so far.
        """
        submission = self._delivering_submission(record)
        if record.status != "abandoned":
            raise InvalidStateError("only an abandoned delivery can be redelivered")
        pending = replace(
            record,
            status="pending",
            attempt_base=max(record.recorded_attempts, default=0),
            enqueued_at=None,
            next_attempt_at=None,
        )
        return Mutation(
            replace(
                self, submission=_with_delivery(submission, _delivery(submission, "delivering"))
            ),
            (_entry(at, actor, "redelivery_requested"),),
            (pending,),
        )

    def _with_submission(
        self,
        status: QuoteStatus,
        delivery: DeliveryState,
        *,
        decided_at: datetime,
        note: str | None,
    ) -> "Quote":
        assert self.submission is not None
        submission = Submission(
            submission_id=self.submission.submission_id,
            carrier_id=self.submission.carrier_id,
            requested_at=self.submission.requested_at,
            decided_at=decided_at,
            decision_note=note,
            delivery=delivery,
        )
        return replace(self, status=status, submission=submission)

    def _delivering_submission(self, record: OutboxRecord) -> Submission:
        """The submission the record belongs to; delivery exists only after an approval."""
        if (
            self.submission is None
            or self.status not in ("approved", "submitted")
            or self.current_event_id != record.event_id
        ):
            raise InvalidStateError("the event does not belong to an approved submission")
        return self.submission


def _entry(
    at: datetime,
    actor: Actor,
    action: str,
    params: dict[str, str | int | float] | None = None,
    *,
    note: str | None = None,
) -> AuditEntry:
    return AuditEntry(
        at=at, actor=actor, action=Coded(code=f"audit.{action}", params=params or {}), note=note
    )


def _key(key_id: str | None) -> dict[str, str | int | float]:
    return {} if key_id is None else {"key_id": key_id}


def _delivery(submission: Submission, status: DeliveryStatus) -> DeliveryState:
    current = submission.delivery
    return DeliveryState(
        status=status,
        attempts=current.attempts,
        receipt_id=current.receipt_id,
        last_error_code=current.last_error_code,
    )


def _with_delivery(submission: Submission, delivery: DeliveryState) -> Submission:
    return Submission(
        submission_id=submission.submission_id,
        carrier_id=submission.carrier_id,
        requested_at=submission.requested_at,
        decided_at=submission.decided_at,
        decision_note=submission.decision_note,
        delivery=delivery,
    )
