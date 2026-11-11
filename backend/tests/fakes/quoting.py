"""In-memory fake of `QuotingFacade`: the five invariants of the contract, no I/O.

Quotes are priced with the canned figures of `builders.py`; the cell and the dataset id of a
stored quote come from its coordinates. Helpers for other plans' tests: `seed_quote`,
`seed_approved`, `audit_actions`, `delivery_attempts`, `abandoned`. `calls` lists every call
received and `enqueued` every event id handed to the dispatcher, in order.

Not modelled: the sweep's abandonment of deliveries silent past the retry window.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from tests.fakes import builders
from tests.fakes.access import Call
from veranico.modules.quoting.contracts import (
    Actor,
    ApprovalView,
    AuditEntry,
    CarrierInfo,
    CreateQuote,
    Decision,
    DeliveryAttempt,
    DeliveryState,
    OutboxDispatcher,
    QuoteSummary,
    QuoteView,
    Submission,
    SubmissionApproved,
    SubmissionPayload,
)
from veranico.shared.kernel.clock import Clock, FixedClock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    ForbiddenError,
    IdempotencyConflictError,
    InvalidArgumentsError,
    InvalidCoverError,
    InvalidStateError,
    NotFoundError,
    UnknownCarrierError,
)
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId
from veranico.shared.kernel.principal import Principal

ApprovalStatus = Literal["pending", "approved", "rejected"]
MAX_NOTE_CHARS = 500
_NOT_STARTED = DeliveryState(
    status="not_started", attempts=0, receipt_id=None, last_error_code=None
)
_APPROVAL_STATUS: dict[str, ApprovalStatus] = {
    "pending_approval": "pending",
    "approved": "approved",
    "submitted": "approved",
    "rejected": "rejected",
}


class FakeQuotingFacade:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        carriers: Sequence[CarrierInfo] = builders.CARRIERS,
        dispatcher: OutboxDispatcher | None = None,
    ) -> None:
        self._clock = clock or FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
        self._carriers = {carrier.carrier_id: carrier for carrier in carriers}
        self._dispatcher = dispatcher
        self._quotes: dict[QuoteId, QuoteView] = {}
        self._idempotency: dict[tuple[WorkspaceId, str], tuple[CreateQuote, QuoteId]] = {}
        self._events: dict[EventId, SubmissionApproved] = {}
        self._event_quote: dict[EventId, QuoteId] = {}
        self._attempts: dict[EventId, list[DeliveryAttempt]] = {}
        self._abandoned: set[EventId] = set()
        self._numbers = {"Q": 0, "S": 0, "E": 0}
        self.calls: list[Call] = []
        self.enqueued: list[EventId] = []

    # Helpers for other plans' tests

    def seed_quote(self, view: QuoteView) -> QuoteView:
        """Store a given quote as it is (plan 05)."""
        self._quotes[view.quote_id] = view
        return view

    def seed_approved(
        self, *, workspace_id: str = "ws-1", carrier_id: str = "carrier-1"
    ) -> EventId:
        """Store an approved quote with its outbox event; return the event id (plan 04).

        The event is committed and not enqueued, as after a crash between the two steps.
        """
        now = self._clock.now()
        quote_id = self._next_quote_id()
        submission = Submission(
            submission_id=self._next_submission_id(),
            carrier_id=carrier_id,
            requested_at=now,
            decided_at=now,
            decision_note=None,
            delivery=_NOT_STARTED.model_copy(update={"status": "delivering"}),
        )
        view = builders.quote_view(
            quote_id=quote_id,
            workspace_id=workspace_id,
            status="approved",
            submission=submission,
            created_at=now,
        )
        self._quotes[view.quote_id] = view
        return self._record_event(view, submission).event_id

    def audit_actions(self, quote_id: QuoteId) -> list[AuditEntry]:
        """The audit entries of a quote, oldest first: actor, action code and parameters."""
        return list(self._quotes[quote_id].audit)

    def delivery_attempts(self, event_id: EventId) -> list[DeliveryAttempt]:
        return list(self._attempts.get(event_id, []))

    def abandoned(self, event_id: EventId) -> bool:
        return event_id in self._abandoned

    # QuotingFacade

    async def create_quote(
        self, principal: Principal, command: CreateQuote, idempotency_key: str | None, actor: Actor
    ) -> QuoteView:
        self.calls.append(("create_quote", (principal, command, idempotency_key, actor)))
        key = (principal.workspace_id, idempotency_key or "")
        if idempotency_key is not None and key in self._idempotency:
            stored_command, quote_id = self._idempotency[key]
            if stored_command != command:
                raise IdempotencyConflictError
            return self._quotes[quote_id]
        if command.cover.limit.amount_cents <= 0:
            raise InvalidCoverError("the limit must be positive")
        now = self._clock.now()
        location = command.location
        dataset_id = builders.point_dataset_for(location.lat, location.lon)
        view = QuoteView(
            quote_id=self._next_quote_id(),
            workspace_id=principal.workspace_id,
            created_at=now,
            status="draft",
            location=builders.quote_location(location.lat, location.lon, location.label).model_copy(
                update={"admin_region": location.admin_region}
            ),
            dataset_id=dataset_id,
            cover=command.cover,
            priced=builders.priced_cover(
                command.cover, dataset_id=dataset_id, options=command.simulation
            ),
            submission=None,
            audit=[AuditEntry(at=now, actor=actor, action=Coded(code="audit.quote_created"))],
        )
        self._quotes[view.quote_id] = view
        if idempotency_key is not None:
            self._idempotency[key] = (command, view.quote_id)
        return view

    async def get_quote(self, principal: Principal, quote_id: QuoteId) -> QuoteView:
        self.calls.append(("get_quote", (principal, quote_id)))
        return self._owned(principal, quote_id)

    async def list_quotes(self, principal: Principal) -> list[QuoteSummary]:
        self.calls.append(("list_quotes", (principal,)))
        return [
            QuoteSummary(
                quote_id=view.quote_id,
                created_at=view.created_at,
                status=view.status,
                location_label=view.location.label,
                premium=view.priced.premium.premium,
            )
            for view in self._quotes.values()
            if view.workspace_id == principal.workspace_id
        ]

    async def request_submission(
        self, principal: Principal, quote_id: QuoteId, carrier_id: str, actor: Actor
    ) -> Submission:
        self.calls.append(("request_submission", (principal, quote_id, carrier_id, actor)))
        view = self._owned(principal, quote_id)
        if view.submission is not None:
            return view.submission
        if view.status != "draft":
            raise InvalidStateError
        if carrier_id not in self._carriers:
            raise UnknownCarrierError
        submission = Submission(
            submission_id=self._next_submission_id(),
            carrier_id=carrier_id,
            requested_at=self._clock.now(),
            decided_at=None,
            decision_note=None,
            delivery=_NOT_STARTED,
        )
        self._update(view, status="pending_approval", submission=submission)
        self._audit(quote_id, actor, "submission_requested", {"carrier_id": carrier_id})
        return submission

    async def list_approvals(
        self, principal: Principal, status: ApprovalStatus | None
    ) -> list[ApprovalView]:
        self.calls.append(("list_approvals", (principal, status)))
        approvals = [
            self._approval(view)
            for view in self._quotes.values()
            if view.workspace_id == principal.workspace_id and view.submission is not None
        ]
        return [approval for approval in approvals if status is None or approval.status == status]

    async def decide(
        self, principal: Principal, approval_id: SubmissionId, decision: Decision
    ) -> ApprovalView:
        self.calls.append(("decide", (principal, approval_id, decision)))
        view = self._owned_approval(principal, approval_id)
        if principal.kind != "browser":
            raise ForbiddenError
        if view.status != "pending_approval":
            raise InvalidStateError
        if decision.note is not None and len(decision.note) > MAX_NOTE_CHARS:
            raise InvalidArgumentsError("the note has more than 500 characters")
        assert view.submission is not None
        submission = view.submission.model_copy(
            update={"decided_at": self._clock.now(), "decision_note": decision.note}
        )
        if not decision.approve:
            self._update(view, status="rejected", submission=submission)
            self._audit(view.quote_id, "human", "rejected", note=decision.note)
            return self._approval(self._quotes[view.quote_id])
        submission = submission.model_copy(
            update={"delivery": _NOT_STARTED.model_copy(update={"status": "delivering"})}
        )
        # State, audit entry and outbox event first (one transaction in the real module),
        # then the dispatcher.
        approved = self._update(view, status="approved", submission=submission)
        self._audit(view.quote_id, "human", "approved", note=decision.note)
        event = self._record_event(approved, submission)
        await self._enqueue(event.event_id)
        return self._approval(self._quotes[view.quote_id])

    async def redeliver(self, principal: Principal, approval_id: SubmissionId) -> ApprovalView:
        self.calls.append(("redeliver", (principal, approval_id)))
        view = self._owned_approval(principal, approval_id)
        assert view.submission is not None
        if view.submission.delivery.status != "abandoned":
            raise InvalidStateError
        events = [event for event, quote in self._event_quote.items() if quote == view.quote_id]
        event_id = events[-1]
        self._abandoned.discard(event_id)
        self._set_delivery(view.quote_id, status="delivering")
        self._audit(view.quote_id, "human", "redelivery_requested")
        await self._enqueue(event_id)
        return self._approval(self._quotes[view.quote_id])

    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None:
        self.calls.append(("append_audit", (principal, quote_id, actor, action)))
        view = self._owned(principal, quote_id)
        entry = AuditEntry(at=self._clock.now(), actor=actor, action=action)
        self._update(view, audit=[*view.audit, entry])

    async def load_event(self, event_id: EventId) -> SubmissionApproved:
        self.calls.append(("load_event", (event_id,)))
        if event_id not in self._events:
            raise NotFoundError
        return self._events[event_id]

    async def record_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        self.calls.append(("record_delivery_attempt", (attempt,)))
        if attempt.event_id not in self._events:
            raise NotFoundError
        recorded = self._attempts.setdefault(attempt.event_id, [])
        if any(previous.attempt == attempt.attempt for previous in recorded):
            return
        recorded.append(attempt)
        quote_id = self._event_quote[attempt.event_id]
        params: dict[str, str | int | float] = {
            "attempt": attempt.attempt,
            "duration_ms": attempt.duration_ms,
        }
        if attempt.status_code is not None:
            params["status_code"] = attempt.status_code
        if attempt.error_code is not None:
            params["error_code"] = attempt.error_code
        self._audit(quote_id, "system", "webhook_attempt", params)
        self._set_delivery(quote_id, attempts=len(recorded), last_error_code=attempt.error_code)
        if attempt.receipt_id is not None:
            self._set_delivery(quote_id, status="delivered", receipt_id=attempt.receipt_id)
            self._update(self._quotes[quote_id], status="submitted")
            self._audit(quote_id, "carrier", "receipt_recorded", {"receipt_id": attempt.receipt_id})

    async def record_delivery_abandoned(self, event_id: EventId) -> None:
        self.calls.append(("record_delivery_abandoned", (event_id,)))
        if event_id not in self._events:
            raise NotFoundError
        if event_id in self._abandoned:
            return
        self._abandoned.add(event_id)
        quote_id = self._event_quote[event_id]
        self._set_delivery(quote_id, status="abandoned")
        self._audit(quote_id, "system", "delivery_abandoned")

    async def sweep_outbox(self, older_than_seconds: int) -> int:
        self.calls.append(("sweep_outbox", (older_than_seconds,)))
        threshold = self._clock.now() - timedelta(seconds=older_than_seconds)
        waiting = [
            event_id
            for event_id, event in self._events.items()
            if event_id not in self.enqueued and event.occurred_at <= threshold
        ]
        for event_id in waiting:
            await self._enqueue(event_id)
        return len(waiting)

    # Internals

    def _next_quote_id(self) -> QuoteId:
        self._numbers["Q"] += 1
        return QuoteId(f"Q-{self._numbers['Q']:06d}")

    def _next_submission_id(self) -> SubmissionId:
        self._numbers["S"] += 1
        return SubmissionId(f"S-{self._numbers['S']:06d}")

    def _next_event_id(self) -> EventId:
        """A UUIDv7-shaped id that counts up, so tests can predict it."""
        self._numbers["E"] += 1
        return EventId(f"0190a8e0-0000-7000-8000-{self._numbers['E']:012d}")

    def _owned(self, principal: Principal, quote_id: QuoteId) -> QuoteView:
        view = self._quotes.get(quote_id)
        if view is None or view.workspace_id != principal.workspace_id:
            raise NotFoundError
        return view

    def _owned_approval(self, principal: Principal, approval_id: SubmissionId) -> QuoteView:
        for view in self._quotes.values():
            if view.submission is not None and view.submission.submission_id == approval_id:
                return self._owned(principal, view.quote_id)
        raise NotFoundError

    def _update(self, view: QuoteView, **changes: object) -> QuoteView:
        updated = self._quotes[view.quote_id].model_copy(update=changes)
        self._quotes[view.quote_id] = updated
        return updated

    def _set_delivery(self, quote_id: QuoteId, **changes: object) -> None:
        view = self._quotes[quote_id]
        assert view.submission is not None
        delivery = view.submission.delivery.model_copy(update=changes)
        self._update(view, submission=view.submission.model_copy(update={"delivery": delivery}))

    def _audit(
        self,
        quote_id: QuoteId,
        actor: Actor,
        action: str,
        params: dict[str, str | int | float] | None = None,
        *,
        note: str | None = None,
    ) -> None:
        view = self._quotes[quote_id]
        entry = AuditEntry(
            at=self._clock.now(),
            actor=actor,
            action=Coded(code=f"audit.{action}", params=params or {}),
            note=note,
        )
        self._update(view, audit=[*view.audit, entry])

    def _approval(self, view: QuoteView) -> ApprovalView:
        assert view.submission is not None
        carrier = self._carriers.get(view.submission.carrier_id)
        return ApprovalView(
            approval_id=view.submission.submission_id,
            quote_id=view.quote_id,
            carrier_id=view.submission.carrier_id,
            carrier_name=carrier.name if carrier else view.submission.carrier_id,
            location_label=view.location.label,
            limit=view.cover.limit,
            premium=view.priced.premium.premium,
            status=_APPROVAL_STATUS[view.status],
            delivery=view.submission.delivery,
            requested_at=view.submission.requested_at,
        )

    def _record_event(self, view: QuoteView, submission: Submission) -> SubmissionApproved:
        event = SubmissionApproved(
            event_id=self._next_event_id(),
            occurred_at=self._clock.now(),
            workspace_id=view.workspace_id,
            carrier_id=submission.carrier_id,
            data=SubmissionPayload(
                quote_id=view.quote_id,
                submission_id=submission.submission_id,
                location=view.location,
                cover=view.cover,
                premium=view.priced.premium.premium,
                rate_on_line=view.priced.premium.rate_on_line,
            ),
        )
        self._events[event.event_id] = event
        self._event_quote[event.event_id] = view.quote_id
        return event

    async def _enqueue(self, event_id: EventId) -> None:
        self.enqueued.append(event_id)
        if self._dispatcher is not None:
            await self._dispatcher.enqueue(event_id)
