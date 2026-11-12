from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import builders
from tests.fakes.quoting import FakeQuotingFacade
from veranico.modules.quoting.contracts import (
    CreateQuote,
    Decision,
    DeliveryAttempt,
    QuoteLocationInput,
    QuoteView,
)
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    ForbiddenError,
    IdempotencyConflictError,
    InvalidArgumentsError,
    InvalidStateError,
    NotFoundError,
    UnknownCarrierError,
)
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId
from veranico.shared.kernel.principal import Principal

BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
API_KEY = Principal(workspace_id=WorkspaceId("ws-1"), kind="api_key", key_id="key-1")
OTHER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")
COMMAND = CreateQuote(
    location=QuoteLocationInput(lat=builders.LAT, lon=builders.LON), cover=builders.cover()
)
APPROVE = Decision(approve=True, note="looks right")


class RecordingDispatcher:
    def __init__(self, quoting: list[FakeQuotingFacade]) -> None:
        self.enqueued: list[EventId] = []
        self.status_when_called: list[str] = []
        self._quoting = quoting

    async def enqueue(self, event_id: EventId) -> None:
        self.enqueued.append(event_id)
        event = await self._quoting[0].load_event(event_id)  # the event is already stored
        quote = await self._quoting[0].get_quote(BROWSER, event.data.quote_id)
        self.status_when_called.append(quote.status)


async def pending(quoting: FakeQuotingFacade) -> tuple[QuoteView, SubmissionId]:
    quote = await quoting.create_quote(API_KEY, COMMAND, None, "api_client")
    submission = await quoting.request_submission(
        API_KEY, quote.quote_id, "carrier-1", "api_client"
    )
    return quote, submission.submission_id


def attempt(event_id: EventId, number: int, receipt_id: str | None = None) -> DeliveryAttempt:
    return DeliveryAttempt(
        event_id=event_id,
        attempt=number,
        status_code=200 if receipt_id else 503,
        error_code=None if receipt_id else "delivery_failed",
        duration_ms=12,
        receipt_id=receipt_id,
    )


def codes(quoting: FakeQuotingFacade, quote_id: QuoteId) -> list[str]:
    return [entry.action.code for entry in quoting.audit_actions(quote_id)]


# create_quote


async def test_create_quote_fills_cell_and_dataset_from_the_coordinates() -> None:
    quoting = FakeQuotingFacade()

    quote = await quoting.create_quote(API_KEY, COMMAND, "key-1", "api_client")

    assert quote.status == "draft"
    assert quote.workspace_id == "ws-1"
    assert quote.location.h3_cell == builders.h3_cell_for(builders.LAT, builders.LON)
    assert quote.dataset_id == builders.point_dataset_for(builders.LAT, builders.LON)
    assert quote.location.label == "-12.5500, -55.7200"  # no label given
    assert quote.priced == builders.priced_cover(COMMAND.cover, dataset_id=quote.dataset_id)
    assert quote.submission is None
    assert [(entry.actor, entry.action) for entry in quote.audit] == [
        ("api_client", Coded(code="audit.quote_created"))
    ]
    assert "dataset_id" not in CreateQuote.model_fields


async def test_the_same_key_with_the_same_payload_returns_the_stored_quote() -> None:
    quoting = FakeQuotingFacade()
    first = await quoting.create_quote(API_KEY, COMMAND, "key-1", "api_client")

    again = await quoting.create_quote(API_KEY, COMMAND, "key-1", "api_client")
    without_key = await quoting.create_quote(API_KEY, COMMAND, None, "api_client")
    other_workspace = await quoting.create_quote(OTHER, COMMAND, "key-1", "agent")

    assert again == first
    assert len(await quoting.list_quotes(API_KEY)) == 2
    assert without_key.quote_id != first.quote_id
    assert other_workspace.quote_id not in {first.quote_id, without_key.quote_id}


async def test_the_same_key_with_another_payload_is_an_idempotency_conflict() -> None:
    quoting = FakeQuotingFacade()
    await quoting.create_quote(API_KEY, COMMAND, "key-1", "api_client")
    changed = COMMAND.model_copy(update={"cover": builders.cover(limit_cents=5_000_000)})

    with pytest.raises(IdempotencyConflictError):
        await quoting.create_quote(API_KEY, changed, "key-1", "api_client")
    assert len(await quoting.list_quotes(API_KEY)) == 1


# request_submission


async def test_request_submission_creates_a_pending_approval() -> None:
    quoting = FakeQuotingFacade()

    quote, approval_id = await pending(quoting)

    stored = await quoting.get_quote(BROWSER, quote.quote_id)
    assert stored.status == "pending_approval"
    assert stored.submission is not None
    assert stored.submission.delivery.status == "not_started"
    assert codes(quoting, quote.quote_id) == ["audit.quote_created", "audit.submission_requested"]
    approvals = await quoting.list_approvals(BROWSER, "pending")
    assert [(a.approval_id, a.status, a.carrier_name) for a in approvals] == [
        (approval_id, "pending", "Fake Carrier One")
    ]
    assert await quoting.list_approvals(BROWSER, "approved") == []
    assert await quoting.list_approvals(OTHER, None) == []


async def test_request_submission_returns_the_existing_submission() -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)

    again = await quoting.request_submission(BROWSER, quote.quote_id, "carrier-2", "human")

    assert again.submission_id == approval_id
    assert again.carrier_id == "carrier-1"
    assert codes(quoting, quote.quote_id).count("audit.submission_requested") == 1


async def test_request_submission_is_invalid_state_unless_the_quote_is_draft() -> None:
    quoting = FakeQuotingFacade()
    quoting.seed_quote(builders.quote_view(quote_id="Q-00000A", status="rejected"))

    with pytest.raises(InvalidStateError):
        await quoting.request_submission(BROWSER, QuoteId("Q-00000A"), "carrier-1", "human")


async def test_request_submission_raises_unknown_carrier() -> None:
    quoting = FakeQuotingFacade()
    quote = await quoting.create_quote(API_KEY, COMMAND, None, "api_client")

    with pytest.raises(UnknownCarrierError):
        await quoting.request_submission(API_KEY, quote.quote_id, "no-such-carrier", "api_client")
    assert (await quoting.get_quote(API_KEY, quote.quote_id)).status == "draft"


# decide


async def test_approval_stores_state_audit_and_event_then_calls_the_dispatcher() -> None:
    holder: list[FakeQuotingFacade] = []
    dispatcher = RecordingDispatcher(holder)
    quoting = FakeQuotingFacade(dispatcher=dispatcher)
    holder.append(quoting)
    quote, approval_id = await pending(quoting)

    approval = await quoting.decide(BROWSER, approval_id, APPROVE)

    stored = await quoting.get_quote(BROWSER, quote.quote_id)
    assert (approval.status, stored.status) == ("approved", "approved")
    assert stored.submission is not None
    assert stored.submission.decision_note == "looks right"
    assert stored.submission.delivery.status == "delivering"
    assert [(e.actor, e.action.code, e.note) for e in quoting.audit_actions(quote.quote_id)][
        -1
    ] == (
        "human",
        "audit.approved",
        "looks right",
    )
    assert len(quoting.enqueued) == 1
    assert dispatcher.enqueued == quoting.enqueued
    assert dispatcher.status_when_called == ["approved"]  # written before the dispatcher ran
    event = await quoting.load_event(quoting.enqueued[0])
    assert event.event_type == "quoting.submission_approved"
    assert (event.workspace_id, event.carrier_id) == ("ws-1", "carrier-1")
    assert (event.data.quote_id, event.data.submission_id) == (quote.quote_id, approval_id)
    assert event.data.premium == stored.priced.premium.premium
    assert event.data.rate_on_line == stored.priced.premium.rate_on_line


async def test_rejection_records_no_event_and_calls_no_dispatcher() -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)

    approval = await quoting.decide(BROWSER, approval_id, Decision(approve=False, note="too dry"))

    assert approval.status == "rejected"
    assert (await quoting.get_quote(BROWSER, quote.quote_id)).status == "rejected"
    assert codes(quoting, quote.quote_id)[-1] == "audit.rejected"
    assert quoting.enqueued == []


@pytest.mark.parametrize(
    "principal",
    [API_KEY, Principal(workspace_id=WorkspaceId("ws-1"), kind="system")],
    ids=["api_key", "system"],
)
async def test_decide_is_forbidden_unless_a_browser_principal(principal: Principal) -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)

    with pytest.raises(ForbiddenError):
        await quoting.decide(principal, approval_id, APPROVE)
    assert (await quoting.get_quote(BROWSER, quote.quote_id)).status == "pending_approval"


async def test_decide_is_invalid_state_unless_pending_approval() -> None:
    quoting = FakeQuotingFacade()
    _, approval_id = await pending(quoting)
    await quoting.decide(BROWSER, approval_id, APPROVE)

    with pytest.raises(InvalidStateError):
        await quoting.decide(BROWSER, approval_id, APPROVE)
    with pytest.raises(InvalidStateError):
        await quoting.decide(BROWSER, approval_id, Decision(approve=False))
    assert len(quoting.enqueued) == 1


async def test_a_note_over_500_characters_is_invalid_arguments() -> None:
    quoting = FakeQuotingFacade()
    _, approval_id = await pending(quoting)

    with pytest.raises(InvalidArgumentsError):
        await quoting.decide(BROWSER, approval_id, Decision(approve=True, note="x" * 501))
    await quoting.decide(BROWSER, approval_id, Decision(approve=True, note="x" * 500))


# isolation


async def test_every_method_with_a_principal_answers_not_found_across_workspaces() -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)
    unknown = QuoteId("Q-ZZZZZZ")

    for quote_id in (quote.quote_id, unknown):
        with pytest.raises(NotFoundError):
            await quoting.get_quote(OTHER, quote_id)
        with pytest.raises(NotFoundError):
            await quoting.request_submission(OTHER, quote_id, "carrier-1", "human")
        with pytest.raises(NotFoundError):
            await quoting.append_audit(OTHER, quote_id, "human", Coded(code="audit.x"))
    with pytest.raises(NotFoundError):
        await quoting.decide(OTHER, approval_id, APPROVE)
    with pytest.raises(NotFoundError):
        await quoting.redeliver(OTHER, approval_id)
    with pytest.raises(NotFoundError):
        await quoting.decide(BROWSER, SubmissionId("S-ZZZZZZ"), APPROVE)
    assert await quoting.list_quotes(OTHER) == []
    assert (await quoting.get_quote(BROWSER, quote.quote_id)).status == "pending_approval"


# delivery bookkeeping


async def test_record_delivery_attempt_is_idempotent_per_event_and_attempt() -> None:
    quoting = FakeQuotingFacade()
    event_id = quoting.seed_approved()
    quote_id = (await quoting.load_event(event_id)).data.quote_id

    await quoting.record_delivery_attempt(attempt(event_id, 1))
    await quoting.record_delivery_attempt(attempt(event_id, 1))
    await quoting.record_delivery_attempt(attempt(event_id, 2))

    assert [a.attempt for a in quoting.delivery_attempts(event_id)] == [1, 2]
    assert codes(quoting, quote_id).count("audit.webhook_attempt") == 2
    quote = await quoting.get_quote(BROWSER, quote_id)
    assert quote.status == "approved"
    assert quote.submission is not None
    assert quote.submission.delivery.attempts == 2
    assert quote.submission.delivery.last_error_code == "delivery_failed"
    entry = quoting.audit_actions(quote_id)[-1]
    assert entry.actor == "system"
    assert entry.action.params == {
        "attempt": 2,
        "duration_ms": 12,
        "status_code": 503,
        "error_code": "delivery_failed",
    }


async def test_a_receipt_moves_the_quote_to_submitted() -> None:
    quoting = FakeQuotingFacade()
    event_id = quoting.seed_approved()
    quote_id = (await quoting.load_event(event_id)).data.quote_id

    await quoting.record_delivery_attempt(attempt(event_id, 1))
    await quoting.record_delivery_attempt(attempt(event_id, 2, receipt_id="R-000001"))
    await quoting.record_delivery_attempt(attempt(event_id, 2, receipt_id="R-000001"))

    quote = await quoting.get_quote(BROWSER, quote_id)
    assert quote.status == "submitted"
    assert quote.submission is not None
    delivery = quote.submission.delivery
    assert (delivery.status, delivery.attempts, delivery.receipt_id) == ("delivered", 2, "R-000001")
    assert delivery.last_error_code is None
    last = quoting.audit_actions(quote_id)[-1]
    assert (last.actor, last.action.code) == ("carrier", "audit.receipt_recorded")
    assert codes(quoting, quote_id).count("audit.receipt_recorded") == 1
    assert (await quoting.list_approvals(BROWSER, "approved"))[0].delivery.status == "delivered"


async def test_an_attempt_or_abandonment_of_an_unknown_event_is_not_found() -> None:
    quoting = FakeQuotingFacade()
    unknown = EventId("0190a8e0-0000-7000-8000-999999999999")

    with pytest.raises(NotFoundError):
        await quoting.load_event(unknown)
    with pytest.raises(NotFoundError):
        await quoting.record_delivery_attempt(attempt(unknown, 1))
    with pytest.raises(NotFoundError):
        await quoting.record_delivery_abandoned(unknown)


async def test_an_abandoned_delivery_can_be_redelivered_by_hand() -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)
    await quoting.decide(BROWSER, approval_id, APPROVE)
    event_id = quoting.enqueued[0]

    with pytest.raises(InvalidStateError):
        await quoting.redeliver(BROWSER, approval_id)  # still delivering
    await quoting.record_delivery_abandoned(event_id)
    await quoting.record_delivery_abandoned(event_id)
    assert quoting.abandoned(event_id)
    abandoned = await quoting.get_quote(BROWSER, quote.quote_id)
    assert abandoned.submission is not None
    assert abandoned.submission.delivery.status == "abandoned"

    approval = await quoting.redeliver(BROWSER, approval_id)

    assert approval.delivery.status == "delivering"
    assert not quoting.abandoned(event_id)
    assert quoting.enqueued == [event_id, event_id]
    assert codes(quoting, quote.quote_id)[-2:] == [
        "audit.delivery_abandoned",
        "audit.redelivery_requested",
    ]


async def test_sweep_enqueues_committed_events_that_were_never_enqueued() -> None:
    clock = FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    quoting = FakeQuotingFacade(clock=clock)
    event_id = quoting.seed_approved()

    too_young = await quoting.sweep_outbox(60)
    clock.advance(timedelta(seconds=61))
    swept = await quoting.sweep_outbox(60)
    again = await quoting.sweep_outbox(60)

    assert (too_young, swept, again) == (0, 1, 0)
    assert quoting.enqueued == [event_id]


# helpers and conventions


async def test_seed_quote_stores_the_given_view_unchanged() -> None:
    quoting = FakeQuotingFacade()
    view = builders.quote_view(quote_id="Q-00000B", workspace_id="ws-2", label="Fazenda Boa Vista")

    quoting.seed_quote(view)

    assert await quoting.get_quote(OTHER, QuoteId("Q-00000B")) == view
    with pytest.raises(NotFoundError):
        await quoting.get_quote(BROWSER, QuoteId("Q-00000B"))


async def test_seed_approved_stores_an_approved_quote_with_its_event() -> None:
    quoting = FakeQuotingFacade()

    event_id = quoting.seed_approved(workspace_id="ws-2", carrier_id="carrier-2")

    event = await quoting.load_event(event_id)
    quote = await quoting.get_quote(OTHER, event.data.quote_id)
    assert quote.status == "approved"
    assert (event.workspace_id, event.carrier_id) == ("ws-2", "carrier-2")
    assert event.data.location == quote.location
    assert quoting.delivery_attempts(event_id) == []
    assert quoting.abandoned(event_id) is False
    assert quoting.enqueued == []


async def test_append_audit_is_read_back_by_audit_actions() -> None:
    quoting = FakeQuotingFacade()
    quote = await quoting.create_quote(API_KEY, COMMAND, None, "agent")
    action = Coded(code="audit.term_sheet_rendered")

    await quoting.append_audit(API_KEY, quote.quote_id, "agent", action)

    assert [(e.actor, e.action) for e in quoting.audit_actions(quote.quote_id)] == [
        ("agent", Coded(code="audit.quote_created")),
        ("agent", action),
    ]


async def test_every_audit_code_is_namespaced() -> None:
    quoting = FakeQuotingFacade()
    quote, approval_id = await pending(quoting)
    await quoting.decide(BROWSER, approval_id, APPROVE)
    event_id = quoting.enqueued[0]
    await quoting.record_delivery_attempt(attempt(event_id, 1))
    await quoting.record_delivery_abandoned(event_id)
    await quoting.redeliver(BROWSER, approval_id)
    await quoting.record_delivery_attempt(attempt(event_id, 2, receipt_id="R-000001"))

    assert codes(quoting, quote.quote_id) == [
        "audit.quote_created",
        "audit.submission_requested",
        "audit.approved",
        "audit.webhook_attempt",
        "audit.delivery_abandoned",
        "audit.redelivery_requested",
        "audit.webhook_attempt",
        "audit.receipt_recorded",
    ]


async def test_calls_lists_what_was_received_in_order() -> None:
    quoting = FakeQuotingFacade()

    quote = await quoting.create_quote(API_KEY, COMMAND, "key-1", "api_client")
    await quoting.get_quote(API_KEY, quote.quote_id)

    assert quoting.calls == [
        ("create_quote", (API_KEY, COMMAND, "key-1", "api_client")),
        ("get_quote", (API_KEY, quote.quote_id)),
    ]
