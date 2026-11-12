from datetime import timedelta

import pytest

from tests.unit.quoting.world import API_KEY, BROWSER, NOW, STRANGER, World
from veranico.modules.quoting.contracts import Decision, DeliveryAttempt
from veranico.shared.kernel.errors import InvalidStateError, NotFoundError
from veranico.shared.kernel.ids import QuoteId, SubmissionId

pytestmark = pytest.mark.req("R-7-6")


@pytest.fixture
def world() -> World:
    return World()


async def _fail(world: World, quote_id: QuoteId, numbers: tuple[int, ...]) -> None:
    """Record failed attempts on the quote's event, as the deliver endpoint does."""
    record = world.record_of(quote_id)
    at = world.clock.now()
    for number in numbers:
        attempt = DeliveryAttempt(
            event_id=record.event_id,
            attempt=number,
            status_code=503,
            error_code="delivery_failed",
            duration_ms=40,
            receipt_id=None,
        )
        await world.quotes.update_for_event(
            record.event_id,
            lambda quote, stored, attempt=attempt: quote.record_attempt(stored, attempt, at=at),
        )


async def test_a_redelivery_resets_the_record_appends_the_entry_and_enqueues(
    world: World,
) -> None:
    approval = await world.approved()
    await _fail(world, approval.quote_id, (1, 2, 3))
    event_id = world.record_of(approval.quote_id).event_id
    at = world.clock.now()
    await world.quotes.update_for_event(
        event_id, lambda quote, record: quote.mark_abandoned(record, at=at)
    )
    world.clock.advance(timedelta(hours=2))

    redelivered = await world.approvals.redeliver(BROWSER, approval.approval_id)

    assert redelivered.status == "approved"
    assert (redelivered.delivery.status, redelivered.delivery.attempts) == ("delivering", 3)
    view = await world.view(approval.quote_id)
    assert view.status == "approved"
    entry = view.audit[-1]
    assert (entry.at, entry.actor) == (NOW + timedelta(hours=2), "human")
    assert entry.action.code == "audit.redelivery_requested"
    record = world.record_of(approval.quote_id)
    assert record.event_id == event_id  # same event: the carrier deduplicates by it
    assert (record.attempt_base, record.recorded_attempts) == (3, (1, 2, 3))
    assert (record.status, record.enqueued_at) == ("enqueued", NOW + timedelta(hours=2))
    assert world.dispatcher.enqueued == [event_id, event_id]


async def test_a_redelivery_whose_enqueue_fails_stays_pending_for_the_sweep(world: World) -> None:
    approval = await world.abandoned()
    world.dispatcher.failure = RuntimeError("queue unavailable")

    redelivered = await world.approvals.redeliver(BROWSER, approval.approval_id)

    assert redelivered.delivery.status == "delivering"
    record = world.record_of(approval.quote_id)
    assert (record.status, record.enqueued_at) == ("pending", None)
    assert world.audit_codes(approval.quote_id)[-1] == "audit.redelivery_requested"


async def test_a_redelivery_is_an_invalid_state_unless_the_delivery_is_abandoned(
    world: World,
) -> None:
    pending = await world.pending()
    rejected = await world.pending()
    await world.approvals.decide(BROWSER, rejected.submission_id, Decision(approve=False))
    delivering = await world.approved()
    redelivered = await world.abandoned()
    await world.approvals.redeliver(BROWSER, redelivered.approval_id)
    enqueued_before = list(world.dispatcher.enqueued)

    for approval_id in (
        pending.submission_id,
        rejected.submission_id,
        delivering.approval_id,
        redelivered.approval_id,  # a second redelivery of a round already in progress
    ):
        with pytest.raises(InvalidStateError):
            await world.approvals.redeliver(BROWSER, approval_id)

    assert world.dispatcher.enqueued == enqueued_before
    assert world.audit_codes(redelivered.quote_id).count("audit.redelivery_requested") == 1


async def test_a_delivered_submission_cannot_be_redelivered(world: World) -> None:
    approval = await world.approved()
    record = world.record_of(approval.quote_id)
    receipt = DeliveryAttempt(
        event_id=record.event_id,
        attempt=1,
        status_code=200,
        error_code=None,
        duration_ms=40,
        receipt_id="R-000001",
    )
    at = world.clock.now()
    await world.quotes.update_for_event(
        record.event_id, lambda quote, stored: quote.record_attempt(stored, receipt, at=at)
    )

    with pytest.raises(InvalidStateError):
        await world.approvals.redeliver(BROWSER, approval.approval_id)

    assert (await world.view(approval.quote_id)).status == "submitted"


@pytest.mark.req("R-10.1-2")
async def test_an_approval_of_another_workspace_or_a_missing_one_is_not_found(
    world: World,
) -> None:
    approval = await world.abandoned()

    with pytest.raises(NotFoundError):
        await world.approvals.redeliver(STRANGER, approval.approval_id)
    with pytest.raises(NotFoundError):
        await world.approvals.redeliver(BROWSER, SubmissionId("S-MSSNG0"))

    assert world.delivery(approval.quote_id).status == "abandoned"


async def test_an_api_key_redelivery_is_recorded_as_an_api_client(world: World) -> None:
    approval = await world.abandoned()

    await world.approvals.redeliver(API_KEY, approval.approval_id)

    entry = (await world.view(approval.quote_id)).audit[-1]
    assert (entry.actor, entry.action.code) == ("api_client", "audit.redelivery_requested")
