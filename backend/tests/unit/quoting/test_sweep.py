from datetime import timedelta

import pytest

from tests.unit.quoting.world import (
    BROWSER,
    NOW,
    RETRY_WINDOW_SECONDS,
    SWEEP_AGE_SECONDS,
    World,
)
from veranico.modules.quoting.contracts import ApprovalView, DeliveryAttempt, DeliveryState
from veranico.shared.kernel.ids import EventId

WINDOW = timedelta(seconds=RETRY_WINDOW_SECONDS)
TICK = timedelta(microseconds=1)


@pytest.fixture
def world() -> World:
    return World()


async def _never_enqueued(world: World) -> tuple[ApprovalView, EventId]:
    """An approval whose enqueue failed: committed, with the record still `pending`."""
    world.dispatcher.failure = RuntimeError("queue unavailable")
    approval = await world.approved()
    world.dispatcher.failure = None
    return approval, world.record_of(approval.quote_id).event_id


async def _enqueued(world: World) -> tuple[ApprovalView, EventId]:
    approval = await world.approved()
    return approval, world.record_of(approval.quote_id).event_id


def _failed(event_id: EventId, number: int) -> DeliveryAttempt:
    return DeliveryAttempt(
        event_id=event_id,
        attempt=number,
        status_code=503,
        error_code="delivery_failed",
        duration_ms=10,
        receipt_id=None,
    )


@pytest.mark.req("R-7-5")
async def test_the_sweep_enqueues_every_pending_record_old_enough_and_then_none(
    world: World,
) -> None:
    first, first_event = await _never_enqueued(world)
    second, second_event = await _never_enqueued(world)
    world.clock.advance(timedelta(seconds=120))

    count = await world.service.sweep_outbox(60)

    assert count == 2
    assert sorted(world.dispatcher.enqueued) == sorted([first_event, second_event])
    for approval in (first, second):
        record = world.record_of(approval.quote_id)
        assert (record.status, record.enqueued_at) == ("enqueued", NOW + timedelta(seconds=120))
    assert await world.service.sweep_outbox(60) == 0
    assert len(world.dispatcher.enqueued) == 2


@pytest.mark.req("R-7-5")
async def test_a_pending_record_younger_than_the_age_is_left_for_a_later_sweep(
    world: World,
) -> None:
    approval, event_id = await _never_enqueued(world)
    world.clock.advance(timedelta(seconds=59))

    assert await world.service.sweep_outbox(60) == 0
    assert world.record_of(approval.quote_id).status == "pending"

    world.clock.advance(timedelta(seconds=1))

    assert await world.service.sweep_outbox(60) == 1
    assert world.dispatcher.enqueued == [event_id]


@pytest.mark.req("R-7-5")
async def test_delivered_abandoned_and_recently_enqueued_records_are_not_touched(
    world: World,
) -> None:
    delivered, delivered_event = await _enqueued(world)
    receipt = _failed(delivered_event, 1).model_copy(
        update={"receipt_id": "R-000001", "status_code": 200, "error_code": None}
    )
    await world.service.record_delivery_attempt(receipt)
    abandoned, abandoned_event = await _enqueued(world)
    await world.service.record_delivery_abandoned(abandoned_event)
    delivering, _ = await _enqueued(world)
    before = dict(world.outbox.records)
    trails = {quote_id: list(trail) for quote_id, trail in world.quotes.trails.items()}
    world.clock.advance(WINDOW)  # exactly the window: not yet silent

    assert await world.service.sweep_outbox(0) == 0

    assert world.outbox.records == before
    assert world.quotes.trails == trails
    assert len(world.dispatcher.enqueued) == 3
    assert world.delivery(delivering.quote_id).status == "delivering"
    assert world.delivery(delivered.quote_id).status == "delivered"
    assert world.delivery(abandoned.quote_id).status == "abandoned"


@pytest.mark.req("R-7-5")
async def test_a_dispatcher_failure_on_one_record_does_not_stop_the_others(world: World) -> None:
    first, first_event = await _never_enqueued(world)
    broken, broken_event = await _never_enqueued(world)
    third, third_event = await _never_enqueued(world)
    world.dispatcher.fail_for = {broken_event}

    count = await world.service.sweep_outbox(0)

    assert count == 2
    assert sorted(world.dispatcher.enqueued) == sorted([first_event, third_event])
    assert world.record_of(broken.quote_id).status == "pending"
    assert world.record_of(first.quote_id).status == "enqueued"
    assert world.record_of(third.quote_id).status == "enqueued"

    world.dispatcher.fail_for = set()

    assert await world.service.sweep_outbox(0) == 1
    assert world.record_of(broken.quote_id).status == "enqueued"


@pytest.mark.req("R-7-13")
@pytest.mark.req("R-7-6")
async def test_an_enqueued_delivery_with_no_attempt_past_the_window_is_abandoned(
    world: World,
) -> None:
    approval, event_id = await _enqueued(world)
    world.clock.advance(WINDOW + TICK)

    count = await world.service.sweep_outbox(SWEEP_AGE_SECONDS)

    assert count == 0  # the count is only the number of events enqueued
    view = await world.view(approval.quote_id)
    assert view.status == "approved"
    assert world.delivery(approval.quote_id) == DeliveryState(
        status="abandoned", attempts=0, receipt_id=None, last_error_code=None
    )
    assert world.record_of(approval.quote_id).status == "abandoned"
    entry = view.audit[-1]
    assert (entry.actor, entry.action.code) == ("system", "audit.delivery_abandoned")
    assert (entry.at, entry.action.params) == (NOW + WINDOW + TICK, {"attempts": 0})

    assert await world.service.sweep_outbox(SWEEP_AGE_SECONDS) == 0  # a second sweep: nothing

    assert world.audit_codes(approval.quote_id).count("audit.delivery_abandoned") == 1
    assert world.dispatcher.enqueued == [event_id]

    redelivered = await world.service.redeliver(BROWSER, approval.approval_id)

    assert redelivered.delivery.status == "delivering"
    assert world.dispatcher.enqueued == [event_id, event_id]
    assert world.record_of(approval.quote_id).status == "enqueued"


@pytest.mark.req("R-7-13")
async def test_a_delivery_whose_last_attempt_is_inside_the_window_is_left_alone(
    world: World,
) -> None:
    approval, event_id = await _enqueued(world)
    world.clock.advance(WINDOW - timedelta(minutes=1))
    await world.service.record_delivery_attempt(_failed(event_id, 1))
    world.clock.advance(timedelta(minutes=2))  # the enqueue is past the window, the attempt not

    assert await world.service.sweep_outbox(SWEEP_AGE_SECONDS) == 0

    assert world.delivery(approval.quote_id).status == "delivering"
    assert world.record_of(approval.quote_id).status == "enqueued"

    world.clock.advance(WINDOW)  # now the last attempt is past the window too

    await world.service.sweep_outbox(SWEEP_AGE_SECONDS)

    assert world.delivery(approval.quote_id).status == "abandoned"
    assert (await world.view(approval.quote_id)).audit[-1].action.params == {"attempts": 1}


@pytest.mark.req("R-7-13")
async def test_a_redelivered_round_gets_a_whole_new_window(world: World) -> None:
    approval, _ = await _enqueued(world)
    world.clock.advance(WINDOW + TICK)
    await world.service.sweep_outbox(SWEEP_AGE_SECONDS)
    await world.service.redeliver(BROWSER, approval.approval_id)
    world.clock.advance(WINDOW)

    await world.service.sweep_outbox(SWEEP_AGE_SECONDS)

    assert world.delivery(approval.quote_id).status == "delivering"

    world.clock.advance(TICK)
    await world.service.sweep_outbox(SWEEP_AGE_SECONDS)

    assert world.delivery(approval.quote_id).status == "abandoned"
    assert world.audit_codes(approval.quote_id).count("audit.delivery_abandoned") == 2


@pytest.mark.req("R-7-5")
@pytest.mark.req("R-7-13")
async def test_reading_the_approvals_queue_sweeps_with_the_configured_age(world: World) -> None:
    never, never_event = await _never_enqueued(world)
    stuck, _ = await _enqueued(world)
    world.clock.advance(timedelta(seconds=SWEEP_AGE_SECONDS - 1))

    await world.service.list_approvals(BROWSER, None)

    assert world.record_of(never.quote_id).status == "pending"  # younger than the age

    world.clock.advance(timedelta(seconds=1))
    await world.service.list_approvals(BROWSER, None)

    assert world.record_of(never.quote_id).status == "enqueued"
    assert world.dispatcher.enqueued[-1] == never_event

    world.clock.advance(WINDOW + TICK)
    approvals = await world.service.list_approvals(BROWSER, "approved")

    by_id = {approval.approval_id: approval for approval in approvals}
    assert by_id[stuck.approval_id].delivery.status == "abandoned"
    assert by_id[stuck.approval_id].status == "approved"
