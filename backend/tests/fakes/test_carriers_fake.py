import pytest

from tests.fakes import builders
from tests.fakes.carriers import FakeCarriersFacade
from tests.fakes.quoting import FakeQuotingFacade
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId, WorkspaceId
from veranico.shared.kernel.principal import Principal

BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")


def test_the_catalogue_is_fixed() -> None:
    carriers = FakeCarriersFacade(FakeQuotingFacade())

    catalog = carriers.catalog()

    assert catalog.all() == list(builders.CARRIERS)
    assert catalog.get("carrier-1") == builders.CARRIERS[0]
    assert catalog.get("no-such-carrier") is None
    assert carriers.catalog().all() == catalog.all()


async def test_deliver_returns_the_scripted_outcomes_and_records_each_attempt() -> None:
    quoting = FakeQuotingFacade()
    carriers = FakeCarriersFacade(quoting)
    event_id = quoting.seed_approved()
    quote_id = (await quoting.load_event(event_id)).data.quote_id
    carriers.script("retryable", "delivered")

    first = await carriers.deliver(event_id, 1)
    second = await carriers.deliver(event_id, 2)

    assert (first.delivered, first.retryable) == (False, True)
    assert (first.attempt.status_code, first.attempt.error_code) == (503, "delivery_failed")
    assert (second.delivered, second.retryable) == (True, False)
    assert second.attempt.receipt_id == "R-000001"
    assert quoting.delivery_attempts(event_id) == [first.attempt, second.attempt]
    assert (await quoting.get_quote(BROWSER, quote_id)).status == "submitted"
    assert carriers.calls == [("deliver", (event_id, 1)), ("deliver", (event_id, 2))]


async def test_a_permanent_failure_is_not_retryable_and_an_unscripted_call_delivers() -> None:
    quoting = FakeQuotingFacade()
    carriers = FakeCarriersFacade(quoting)
    event_id = quoting.seed_approved()
    carriers.script("permanent")

    refused = await carriers.deliver(event_id, 1)
    delivered = await carriers.deliver(event_id, 2)

    assert (refused.delivered, refused.retryable, refused.attempt.status_code) == (
        False,
        False,
        400,
    )
    assert delivered.delivered


async def test_delivering_an_unknown_event_is_not_found() -> None:
    carriers = FakeCarriersFacade(FakeQuotingFacade())

    with pytest.raises(NotFoundError):
        await carriers.deliver(EventId("0190a8e0-0000-7000-8000-999999999999"), 1)
