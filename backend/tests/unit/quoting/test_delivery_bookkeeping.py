from datetime import timedelta

import pytest

from tests.unit.quoting.world import BROWSER, NOW, World
from veranico.modules.quoting.contracts import DeliveryAttempt, DeliveryState, QuotingFacade
from veranico.shared.kernel.errors import InvalidStateError, NotFoundError
from veranico.shared.kernel.ids import EventId

UNKNOWN_EVENT = EventId("0190a8e0-0000-7000-8000-00000000dead")


@pytest.fixture
def world() -> World:
    return World()


def _attempt(event_id: EventId, number: int, *, receipt_id: str | None = None) -> DeliveryAttempt:
    return DeliveryAttempt(
        event_id=event_id,
        attempt=number,
        status_code=200 if receipt_id else 503,
        error_code=None if receipt_id else "delivery_failed",
        duration_ms=87,
        receipt_id=receipt_id,
    )


async def _approved_event(world: World) -> tuple[EventId, World]:
    approval = await world.approved()
    return world.record_of(approval.quote_id).event_id, world


def test_the_service_satisfies_the_whole_facade(world: World) -> None:
    facade: QuotingFacade = world.service

    assert facade is world.service


async def test_the_stored_event_is_loaded_and_an_unknown_id_is_not_found(world: World) -> None:
    approval = await world.approved()
    record = world.record_of(approval.quote_id)

    event = await world.service.load_event(record.event_id)

    assert event == record.event
    assert (event.data.quote_id, event.data.submission_id) == (
        approval.quote_id,
        approval.approval_id,
    )
    assert event.carrier_id == "carrier-1"
    with pytest.raises(NotFoundError):
        await world.service.load_event(UNKNOWN_EVENT)


@pytest.mark.req("R-6-6")
@pytest.mark.req("R-7-4")
async def test_a_failed_attempt_is_one_system_entry_and_increments_the_attempts(
    world: World,
) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    world.clock.advance(timedelta(seconds=30))

    await world.service.record_delivery_attempt(_attempt(event_id, 1))

    view = await world.view(approval.quote_id)
    entry = view.audit[-1]
    assert (entry.at, entry.actor) == (NOW + timedelta(seconds=30), "system")
    assert entry.action.code == "audit.webhook_attempt"
    assert entry.action.params == {
        "attempt": 1,
        "duration_ms": 87,
        "status_code": 503,
        "error_code": "delivery_failed",
    }
    assert view.status == "approved"
    assert world.delivery(approval.quote_id) == DeliveryState(
        status="delivering", attempts=1, receipt_id=None, last_error_code="delivery_failed"
    )
    record = world.record_of(approval.quote_id)
    assert (record.recorded_attempts, record.last_attempt_at) == (
        (1,),
        NOW + timedelta(seconds=30),
    )

    await world.service.record_delivery_attempt(_attempt(event_id, 2))

    assert world.delivery(approval.quote_id).attempts == 2
    assert world.audit_codes(approval.quote_id).count("audit.webhook_attempt") == 2


@pytest.mark.req("R-7-4")
async def test_the_same_event_and_attempt_recorded_twice_changes_nothing(world: World) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await world.service.record_delivery_attempt(_attempt(event_id, 1))
    before = (await world.view(approval.quote_id), world.record_of(approval.quote_id))
    world.clock.advance(timedelta(minutes=1))

    await world.service.record_delivery_attempt(_attempt(event_id, 1))
    await world.service.record_delivery_attempt(_attempt(event_id, 1, receipt_id="R-000001"))

    assert (await world.view(approval.quote_id), world.record_of(approval.quote_id)) == before


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
async def test_an_attempt_with_a_receipt_submits_the_quote_and_delivers_the_record(
    world: World,
) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await world.service.record_delivery_attempt(_attempt(event_id, 1))

    await world.service.record_delivery_attempt(_attempt(event_id, 2, receipt_id="R-000001"))

    view = await world.view(approval.quote_id)
    assert view.status == "submitted"
    assert world.delivery(approval.quote_id) == DeliveryState(
        status="delivered", attempts=2, receipt_id="R-000001", last_error_code=None
    )
    assert [(e.actor, e.action.code) for e in view.audit[-2:]] == [
        ("system", "audit.webhook_attempt"),
        ("carrier", "audit.receipt_recorded"),
    ]
    assert view.audit[-1].action.params == {"receipt_id": "R-000001"}
    assert world.record_of(approval.quote_id).status == "delivered"
    (listed,) = await world.service.list_approvals(BROWSER, "approved")
    assert (listed.status, listed.delivery.status) == ("approved", "delivered")


async def test_a_failed_attempt_arriving_after_the_receipt_does_not_regress(world: World) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await world.service.record_delivery_attempt(_attempt(event_id, 2, receipt_id="R-000001"))
    delivered = world.delivery(approval.quote_id)

    await world.service.record_delivery_attempt(_attempt(event_id, 1))
    await world.service.record_delivery_abandoned(event_id)

    assert (await world.view(approval.quote_id)).status == "submitted"
    assert world.delivery(approval.quote_id) == delivered
    assert world.record_of(approval.quote_id).status == "delivered"
    assert "audit.delivery_abandoned" not in world.audit_codes(approval.quote_id)


@pytest.mark.req("R-7-6")
async def test_an_abandonment_keeps_the_quote_approved_and_is_recorded_once(world: World) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await world.service.record_delivery_attempt(_attempt(event_id, 1))

    for _ in range(3):
        await world.service.record_delivery_abandoned(event_id)

    view = await world.view(approval.quote_id)
    assert view.status == "approved"
    assert world.delivery(approval.quote_id) == DeliveryState(
        status="abandoned", attempts=1, receipt_id=None, last_error_code="delivery_failed"
    )
    assert world.audit_codes(approval.quote_id).count("audit.delivery_abandoned") == 1
    entry = view.audit[-1]
    assert (entry.actor, entry.action.params) == ("system", {"attempts": 1})
    assert world.record_of(approval.quote_id).status == "abandoned"
    (listed,) = await world.service.list_approvals(BROWSER, "approved")
    assert listed.delivery.status == "abandoned"


@pytest.mark.req("R-7-6")
async def test_the_queue_calling_after_the_abandonment_is_recorded_and_stays_abandoned(
    world: World,
) -> None:
    """The queue stops by its own limits, not the application's: late calls keep arriving."""
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await world.service.record_delivery_attempt(_attempt(event_id, 1))
    await world.service.record_delivery_abandoned(event_id)

    await world.service.record_delivery_attempt(_attempt(event_id, 2))

    assert world.delivery(approval.quote_id).status == "abandoned"
    assert world.delivery(approval.quote_id).attempts == 2
    assert world.record_of(approval.quote_id).status == "abandoned"

    await world.service.record_delivery_attempt(_attempt(event_id, 3, receipt_id="R-000001"))

    assert (await world.view(approval.quote_id)).status == "submitted"
    assert world.delivery(approval.quote_id).status == "delivered"


@pytest.mark.req("R-7-6")
async def test_attempts_of_a_redelivered_round_continue_after_the_recorded_ones(
    world: World,
) -> None:
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    for number in (1, 2):
        await world.service.record_delivery_attempt(_attempt(event_id, number))
    await world.service.record_delivery_abandoned(event_id)
    await world.service.redeliver(BROWSER, approval.approval_id)
    base = world.record_of(approval.quote_id).attempt_base

    # The deliver endpoint numbers the new round from the base: base + retry count + 1.
    await world.service.record_delivery_attempt(_attempt(event_id, base + 1, receipt_id="R-000001"))

    assert base == 2
    assert world.delivery(approval.quote_id) == DeliveryState(
        status="delivered", attempts=3, receipt_id="R-000001", last_error_code=None
    )
    assert world.record_of(approval.quote_id).recorded_attempts == (1, 2, 3)


async def test_bookkeeping_for_an_unknown_event_is_not_found(world: World) -> None:
    with pytest.raises(NotFoundError):
        await world.service.record_delivery_attempt(_attempt(UNKNOWN_EVENT, 1))
    with pytest.raises(NotFoundError):
        await world.service.record_delivery_abandoned(UNKNOWN_EVENT)


async def test_an_error_inside_the_mutation_writes_nothing(world: World) -> None:
    """A record whose quote no longer points at it: refused, with no partial write."""
    approval = await world.approved()
    record = world.record_of(approval.quote_id)
    stale = record.event.model_copy(update={"event_id": UNKNOWN_EVENT})
    world.outbox.records[UNKNOWN_EVENT] = type(record)(
        event=stale, quote_id=record.quote_id, status="enqueued", created_at=record.created_at
    )
    trail = list(world.audit_codes(approval.quote_id))

    with pytest.raises(InvalidStateError):
        await world.service.record_delivery_attempt(_attempt(UNKNOWN_EVENT, 1))

    assert world.audit_codes(approval.quote_id) == trail
    assert world.outbox.records[UNKNOWN_EVENT].recorded_attempts == ()
