from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import builders
from veranico.modules.quoting.contracts import (
    Decision,
    DeliveryAttempt,
    DeliveryState,
    QuoteStatus,
    SubmissionApproved,
)
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.domain.quote import MAX_NOTE_CHARS, Mutation, Quote
from veranico.shared.kernel.errors import InvalidArgumentsError, InvalidStateError
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
EVENT_ID = EventId("0190a8e0-0000-7000-8000-000000000001")
OTHER_EVENT_ID = EventId("0190a8e0-0000-7000-8000-000000000002")
SUBMISSION_ID = SubmissionId("S-000001")


def _draft() -> Quote:
    view = builders.quote_view(priced=builders.priced_cover(gap_to_burn_cost_cents=-1_234))
    return Quote.draft(
        quote_id=view.quote_id,
        workspace_id=view.workspace_id,
        created_at=view.created_at,
        location=view.location,
        dataset_id=view.dataset_id,
        cover=view.cover,
        priced=view.priced,
        actor="api_client",
    ).quote


def _pending() -> Quote:
    return (
        _draft()
        .request_submission(
            submission_id=SUBMISSION_ID, carrier_id="carrier-1", actor="agent", at=NOW
        )
        .quote
    )


def _approved() -> tuple[Quote, OutboxRecord]:
    mutation = _pending().decide(Decision(approve=True), event_id=EVENT_ID, at=NOW)
    return mutation.quote, mutation.outbox[0]


def _rejected() -> Quote:
    return _pending().decide(Decision(approve=False), event_id=EVENT_ID, at=NOW).quote


def _attempt(
    number: int,
    *,
    receipt_id: str | None = None,
    status_code: int | None = 503,
    error_code: str | None = "delivery_failed",
) -> DeliveryAttempt:
    if receipt_id is not None:
        status_code, error_code = 200, None
    return DeliveryAttempt(
        event_id=EVENT_ID,
        attempt=number,
        status_code=status_code,
        error_code=error_code,
        duration_ms=120,
        receipt_id=receipt_id,
    )


def _submitted() -> tuple[Quote, OutboxRecord]:
    quote, record = _approved()
    mutation = quote.record_attempt(record, _attempt(1, receipt_id="R-000001"), at=NOW)
    return mutation.quote, mutation.outbox[0]


def _abandoned() -> tuple[Quote, OutboxRecord]:
    quote, record = _approved()
    failed = quote.record_attempt(record.mark_enqueued(NOW), _attempt(1), at=NOW)
    mutation = failed.quote.mark_abandoned(failed.outbox[0], at=NOW)
    return mutation.quote, mutation.outbox[0]


def _codes(mutation: Mutation) -> list[tuple[str, str]]:
    return [(entry.actor, entry.action.code) for entry in mutation.audit]


def _delivery(quote: Quote) -> DeliveryState:
    assert quote.submission is not None
    return quote.submission.delivery


# Allowed transitions


@pytest.mark.req("R-6-1")
@pytest.mark.req("R-6-6")
def test_a_draft_holds_every_stored_field_and_one_creation_entry() -> None:
    source = builders.quote_view(workspace_id="ws-7")

    mutation = Quote.draft(
        quote_id=source.quote_id,
        workspace_id=source.workspace_id,
        created_at=NOW,
        location=source.location,
        dataset_id=source.dataset_id,
        cover=source.cover,
        priced=source.priced,
        actor="api_client",
        key_id="key-1",
        idempotency_ref="ref-1",
    )

    view = mutation.quote.view(list(mutation.audit))
    assert view == source.model_copy(update={"created_at": NOW, "audit": list(mutation.audit)})
    assert view.status == "draft"
    assert view.submission is None
    assert mutation.quote.idempotency_ref == "ref-1"
    assert mutation.outbox == ()
    (entry,) = mutation.audit
    assert (entry.at, entry.actor, entry.note) == (NOW, "api_client", None)
    assert entry.action.code == "audit.quote_created"
    assert entry.action.params == {"key_id": "key-1"}


@pytest.mark.req("R-6-6")
def test_a_creation_without_an_api_key_omits_the_key_parameter() -> None:
    view = builders.quote_view()

    mutation = Quote.draft(
        quote_id=view.quote_id,
        workspace_id=view.workspace_id,
        created_at=NOW,
        location=view.location,
        dataset_id=view.dataset_id,
        cover=view.cover,
        priced=view.priced,
        actor="agent",
    )

    assert _codes(mutation) == [("agent", "audit.quote_created")]
    assert mutation.audit[0].action.params == {}


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
def test_requesting_a_submission_moves_a_draft_to_pending_approval() -> None:
    mutation = _draft().request_submission(
        submission_id=SUBMISSION_ID,
        carrier_id="carrier-1",
        actor="api_client",
        at=LATER,
        key_id="k",
    )

    assert mutation.quote.status == "pending_approval"
    submission = mutation.quote.submission
    assert submission is not None
    assert (submission.submission_id, submission.carrier_id) == (SUBMISSION_ID, "carrier-1")
    assert (submission.requested_at, submission.decided_at) == (LATER, None)
    assert submission.delivery == DeliveryState(
        status="not_started", attempts=0, receipt_id=None, last_error_code=None
    )
    assert _codes(mutation) == [("api_client", "audit.submission_requested")]
    assert mutation.audit[0].action.params == {"carrier_id": "carrier-1", "key_id": "k"}
    assert mutation.audit[0].at == LATER
    assert mutation.outbox == ()


@pytest.mark.req("R-6-5")
def test_requesting_again_returns_the_quote_unchanged_even_for_another_carrier() -> None:
    pending = _pending()

    mutation = pending.request_submission(
        submission_id=SubmissionId("S-000002"), carrier_id="carrier-2", actor="agent", at=LATER
    )

    assert mutation == Mutation(pending)


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
def test_an_approval_yields_the_state_one_audit_entry_and_one_outbox_record() -> None:
    pending = _pending()

    mutation = pending.decide(
        Decision(approve=True, note="looks right"), event_id=EVENT_ID, at=LATER
    )

    approved = mutation.quote
    assert approved.status == "approved"
    assert approved.current_event_id == EVENT_ID
    assert approved.submission is not None
    assert approved.submission.decided_at == LATER
    assert approved.submission.decision_note == "looks right"
    assert _delivery(approved).status == "delivering"
    assert _codes(mutation) == [("human", "audit.approved")]
    assert mutation.audit[0].note == "looks right"
    assert mutation.audit[0].action.params == {}
    (record,) = mutation.outbox
    assert (record.status, record.quote_id, record.created_at) == (
        "pending",
        QuoteId("Q-000001"),
        LATER,
    )
    assert (record.recorded_attempts, record.attempt_base) == ((), 0)
    assert (record.enqueued_at, record.last_attempt_at, record.next_attempt_at) == (None,) * 3


@pytest.mark.req("R-6-1")
def test_the_approved_event_copies_the_quote_figures_without_change() -> None:
    pending = _pending()

    (record,) = pending.decide(Decision(approve=True), event_id=EVENT_ID, at=LATER).outbox

    event = record.event
    assert isinstance(event, SubmissionApproved)
    assert (event.event_id, event.occurred_at) == (EVENT_ID, LATER)
    assert (event.event_type, event.version) == ("quoting.submission_approved", 1)
    assert event.workspace_id == WorkspaceId("ws-1")
    assert event.carrier_id == "carrier-1"
    assert event.data.quote_id == pending.quote_id
    assert event.data.submission_id == SUBMISSION_ID
    assert event.data.location == pending.location
    assert event.data.cover == pending.cover
    assert event.data.premium == pending.priced.premium.premium
    assert event.data.rate_on_line == pending.priced.premium.rate_on_line


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
def test_a_rejection_yields_one_audit_entry_and_no_outbox_record() -> None:
    mutation = _pending().decide(Decision(approve=False, note="no"), event_id=EVENT_ID, at=LATER)

    assert mutation.quote.status == "rejected"
    assert mutation.quote.current_event_id is None
    assert mutation.quote.submission is not None
    assert mutation.quote.submission.decided_at == LATER
    assert mutation.quote.submission.decision_note == "no"
    assert _delivery(mutation.quote).status == "not_started"
    assert _codes(mutation) == [("human", "audit.rejected")]
    assert mutation.audit[0].note == "no"
    assert mutation.outbox == ()


def test_a_note_of_the_maximum_length_is_accepted_and_one_more_character_is_not() -> None:
    pending = _pending()

    accepted = pending.decide(
        Decision(approve=False, note="n" * MAX_NOTE_CHARS), event_id=EVENT_ID, at=NOW
    )
    with pytest.raises(InvalidArgumentsError):
        pending.decide(
            Decision(approve=True, note="n" * (MAX_NOTE_CHARS + 1)), event_id=EVENT_ID, at=NOW
        )

    assert MAX_NOTE_CHARS == 500
    assert accepted.quote.status == "rejected"


# Delivery bookkeeping


@pytest.mark.req("R-6-6")
@pytest.mark.req("R-7-4")
def test_a_failed_attempt_is_one_audit_entry_and_counts_as_an_attempt() -> None:
    quote, record = _approved()

    mutation = quote.record_attempt(record.mark_enqueued(NOW), _attempt(1), at=LATER)

    assert mutation.quote.status == "approved"
    assert _delivery(mutation.quote) == DeliveryState(
        status="delivering", attempts=1, receipt_id=None, last_error_code="delivery_failed"
    )
    assert _codes(mutation) == [("system", "audit.webhook_attempt")]
    assert mutation.audit[0].action.params == {
        "attempt": 1,
        "duration_ms": 120,
        "status_code": 503,
        "error_code": "delivery_failed",
    }
    (recorded,) = mutation.outbox
    assert (recorded.status, recorded.recorded_attempts) == ("enqueued", (1,))
    assert recorded.last_attempt_at == LATER


@pytest.mark.req("R-6-6")
def test_an_attempt_without_a_status_code_omits_the_parameter() -> None:
    quote, record = _approved()

    mutation = quote.record_attempt(
        record, _attempt(1, status_code=None, error_code="timeout"), at=NOW
    )

    assert mutation.audit[0].action.params == {
        "attempt": 1,
        "duration_ms": 120,
        "error_code": "timeout",
    }


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
def test_a_receipt_submits_the_quote_and_marks_the_delivery_delivered() -> None:
    quote, record = _approved()
    failed = quote.record_attempt(record.mark_enqueued(NOW), _attempt(1), at=NOW)

    mutation = failed.quote.record_attempt(
        failed.outbox[0], _attempt(2, receipt_id="R-000001"), at=LATER
    )

    assert mutation.quote.status == "submitted"
    assert _delivery(mutation.quote) == DeliveryState(
        status="delivered", attempts=2, receipt_id="R-000001", last_error_code=None
    )
    assert _codes(mutation) == [
        ("system", "audit.webhook_attempt"),
        ("carrier", "audit.receipt_recorded"),
    ]
    assert mutation.audit[0].action.params == {"attempt": 2, "duration_ms": 120, "status_code": 200}
    assert mutation.audit[1].action.params == {"receipt_id": "R-000001"}
    (delivered,) = mutation.outbox
    assert (delivered.status, delivered.recorded_attempts) == ("delivered", (1, 2))


def test_the_same_attempt_number_recorded_twice_changes_nothing() -> None:
    quote, record = _approved()
    first = quote.record_attempt(record, _attempt(1), at=NOW)

    again = first.quote.record_attempt(first.outbox[0], _attempt(1), at=LATER)
    as_receipt = first.quote.record_attempt(
        first.outbox[0], _attempt(1, receipt_id="R-000001"), at=LATER
    )

    assert again == Mutation(first.quote)
    assert as_receipt == Mutation(first.quote)


def test_a_failed_attempt_after_the_receipt_adds_an_entry_and_changes_no_state() -> None:
    submitted, record = _submitted()

    mutation = submitted.record_attempt(record, _attempt(2), at=LATER)

    assert mutation.quote == submitted
    assert _codes(mutation) == [("system", "audit.webhook_attempt")]
    (recorded,) = mutation.outbox
    assert (recorded.status, recorded.recorded_attempts) == ("delivered", (1, 2))


def test_a_second_receipt_after_the_first_records_no_second_receipt() -> None:
    submitted, record = _submitted()

    mutation = submitted.record_attempt(record, _attempt(2, receipt_id="R-000001"), at=LATER)

    assert mutation.quote == submitted
    assert _codes(mutation) == [("system", "audit.webhook_attempt")]


@pytest.mark.req("R-7-6")
def test_an_abandonment_keeps_the_quote_approved_with_the_marker() -> None:
    quote, record = _approved()
    failed = quote.record_attempt(record.mark_enqueued(NOW), _attempt(1), at=NOW)

    mutation = failed.quote.mark_abandoned(failed.outbox[0], at=LATER)

    assert mutation.quote.status == "approved"
    assert _delivery(mutation.quote) == DeliveryState(
        status="abandoned", attempts=1, receipt_id=None, last_error_code="delivery_failed"
    )
    assert _codes(mutation) == [("system", "audit.delivery_abandoned")]
    assert mutation.audit[0].action.params == {"attempts": 1}
    assert mutation.audit[0].at == LATER
    (abandoned,) = mutation.outbox
    assert abandoned.status == "abandoned"


def test_abandoning_twice_or_after_the_delivery_is_a_no_op() -> None:
    abandoned, abandoned_record = _abandoned()
    submitted, delivered_record = _submitted()

    assert abandoned.mark_abandoned(abandoned_record, at=LATER) == Mutation(abandoned)
    assert submitted.mark_abandoned(delivered_record, at=LATER) == Mutation(submitted)


def test_a_failed_attempt_after_the_abandonment_keeps_it_abandoned() -> None:
    abandoned, record = _abandoned()

    mutation = abandoned.record_attempt(record, _attempt(2), at=LATER)

    assert mutation.quote.status == "approved"
    assert _delivery(mutation.quote).status == "abandoned"
    assert _delivery(mutation.quote).attempts == 2
    assert mutation.outbox[0].status == "abandoned"


def test_a_receipt_after_the_abandonment_still_submits_the_quote() -> None:
    abandoned, record = _abandoned()

    mutation = abandoned.record_attempt(record, _attempt(2, receipt_id="R-000001"), at=LATER)

    assert mutation.quote.status == "submitted"
    assert _delivery(mutation.quote) == DeliveryState(
        status="delivered", attempts=2, receipt_id="R-000001", last_error_code=None
    )
    assert mutation.outbox[0].status == "delivered"


@pytest.mark.req("R-7-6")
def test_a_redelivery_starts_a_new_round_after_the_recorded_attempts() -> None:
    quote, record = _approved()
    for number in (1, 2, 3):
        step = quote.record_attempt(record.mark_enqueued(NOW), _attempt(number), at=NOW)
        quote, record = step.quote, step.outbox[0]
    step = quote.mark_abandoned(record, at=NOW)
    quote, record = step.quote, step.outbox[0].after_dispatch(LATER).after_dispatch(LATER)

    mutation = quote.request_redelivery(record, actor="human", at=LATER)

    assert (record.round, record.dispatch_count) == (0, 2)
    assert (mutation.outbox[0].round, mutation.outbox[0].dispatch_count) == (1, 0)
    assert mutation.quote.status == "approved"
    assert _delivery(mutation.quote).status == "delivering"
    assert _delivery(mutation.quote).attempts == 3
    assert _codes(mutation) == [("human", "audit.redelivery_requested")]
    assert mutation.audit[0].action.params == {}
    (pending,) = mutation.outbox
    assert (pending.status, pending.attempt_base) == ("pending", 3)
    assert pending.event_id == EVENT_ID  # the carrier deduplicates by event id
    assert pending.recorded_attempts == (1, 2, 3)
    assert (pending.enqueued_at, pending.next_attempt_at) == (None, None)


def test_a_redelivery_is_refused_unless_the_delivery_is_abandoned() -> None:
    approved, pending_record = _approved()
    submitted, delivered_record = _submitted()

    for quote, record in (
        (approved, pending_record),
        (approved, pending_record.mark_enqueued(NOW)),
        (submitted, delivered_record),
    ):
        with pytest.raises(InvalidStateError):
            quote.request_redelivery(record, actor="human", at=LATER)


# Every other (status, operation) pair


@pytest.mark.req("R-6-2")
@pytest.mark.parametrize("status", ["pending_approval", "approved", "rejected", "submitted"])
def test_a_submission_cannot_be_requested_outside_draft(status: QuoteStatus) -> None:
    quote = replace(_draft(), status=status)

    with pytest.raises(InvalidStateError):
        quote.request_submission(
            submission_id=SUBMISSION_ID, carrier_id="carrier-1", actor="agent", at=NOW
        )


@pytest.mark.req("R-6-2")
@pytest.mark.parametrize("approve", [True, False])
def test_a_decision_is_refused_unless_the_approval_is_pending(approve: bool) -> None:
    quotes = [_draft(), _approved()[0], _rejected(), _submitted()[0], _abandoned()[0]]

    for quote in quotes:
        with pytest.raises(InvalidStateError):
            quote.decide(Decision(approve=approve), event_id=OTHER_EVENT_ID, at=LATER)


@pytest.mark.req("R-6-2")
def test_delivery_operations_are_refused_before_an_approval() -> None:
    _, record = _approved()

    for quote in (_draft(), _pending(), _rejected()):
        with pytest.raises(InvalidStateError):
            quote.record_attempt(record, _attempt(1, receipt_id="R-000001"), at=NOW)
        with pytest.raises(InvalidStateError):
            quote.mark_abandoned(record, at=NOW)
        with pytest.raises(InvalidStateError):
            quote.request_redelivery(replace(record, status="abandoned"), actor="human", at=NOW)


def test_delivery_operations_are_refused_for_an_event_of_another_approval() -> None:
    approved, record = _approved()
    foreign = replace(record, event=record.event.model_copy(update={"event_id": OTHER_EVENT_ID}))

    with pytest.raises(InvalidStateError):
        approved.record_attempt(foreign, _attempt(1), at=NOW)
    with pytest.raises(InvalidStateError):
        approved.mark_abandoned(foreign, at=NOW)
