"""SPEC section 7: a delivery never stays in progress forever.

The queue accepted the event and cannot reach the deliver endpoint, so no attempt and no
abandonment is ever recorded. The sweep is then the one that ends the delivery, once the
queue's whole retry window has passed in silence; a person may ask for a new round.
"""

from datetime import timedelta

import pytest

from tests.api.quoting.conftest import V1, QuotingApi
from tests.failure.quoting.conftest import (
    SERVICE,
    SWEEP,
    approval_of,
    audit_codes,
    decide,
    outbox_statuses,
    pending,
    quote_of,
)

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-7-13")]

RETRY_WINDOW = timedelta(seconds=3_600)  # the default `delivery.retry_window_seconds`


@pytest.mark.req("R-7-6")
async def test_the_sweep_route_abandons_a_delivery_silent_past_the_retry_window(
    api: QuotingApi,
) -> None:
    session = await api.session()
    quote_id, approval_id = await pending(session)
    decided = await decide(session, approval_id, True)
    (event_id,) = api.dispatcher.enqueued  # accepted by the queue, never delivered
    service = api.client(SERVICE)

    api.clock.advance(RETRY_WINDOW)  # exactly the window: not yet past it
    inside = await service.post(SWEEP)
    quote_inside = await quote_of(session, quote_id)

    assert decided.status_code == 200
    assert (inside.status_code, inside.json()) == (200, {"enqueued": 0})
    assert quote_inside["submission"]["delivery"]["status"] == "delivering"
    assert "audit.delivery_abandoned" not in audit_codes(quote_inside)
    assert api.dispatcher.enqueued == [event_id]

    api.clock.advance(timedelta(seconds=1))
    past = await service.post(SWEEP)
    again = await service.post(SWEEP)

    assert (past.status_code, again.status_code) == (200, 200)
    approval = await approval_of(session, approval_id)
    assert approval["status"] == "approved"
    assert approval["delivery"] == {
        "status": "abandoned",
        "attempts": 0,
        "receipt_id": None,
        "last_error_code": None,
    }
    quote = await quote_of(session, quote_id)
    assert quote["status"] == "approved"
    assert audit_codes(quote).count("audit.delivery_abandoned") == 1
    assert await outbox_statuses(api, quote_id) == ["abandoned"]
    assert api.dispatcher.enqueued == [event_id]  # abandoning enqueues nothing

    redelivered = await session.browser.post(f"{V1}/approvals/{approval_id}/redeliver")

    assert redelivered.status_code == 200
    assert redelivered.json()["delivery"]["status"] == "delivering"
    assert api.dispatcher.enqueued == [event_id, event_id]
    after = await quote_of(session, quote_id)
    assert after["status"] == "approved"
    assert audit_codes(after)[-2:] == ["audit.delivery_abandoned", "audit.redelivery_requested"]


async def test_the_approval_queue_alone_abandons_a_stuck_delivery(api: QuotingApi) -> None:
    session = await api.session()
    quote_id, approval_id = await pending(session)
    await decide(session, approval_id, True)
    (event_id,) = api.dispatcher.enqueued

    api.clock.advance(RETRY_WINDOW)
    inside = await approval_of(session, approval_id)
    api.clock.advance(timedelta(seconds=1))
    await approval_of(session, approval_id)  # this call's sweep abandons the delivery
    shown = await approval_of(session, approval_id)

    assert inside["delivery"]["status"] == "delivering"
    assert (shown["status"], shown["delivery"]["status"]) == ("approved", "abandoned")
    quote = await quote_of(session, quote_id)
    assert quote["status"] == "approved"
    assert audit_codes(quote).count("audit.delivery_abandoned") == 1
    assert api.dispatcher.enqueued == [event_id]


async def test_a_new_round_that_is_stuck_too_is_abandoned_again(api: QuotingApi) -> None:
    session = await api.session()
    quote_id, approval_id = await pending(session)
    await decide(session, approval_id, True)
    service = api.client(SERVICE)
    api.clock.advance(RETRY_WINDOW + timedelta(seconds=1))
    await service.post(SWEEP)
    await session.browser.post(f"{V1}/approvals/{approval_id}/redeliver")

    await service.post(SWEEP)  # the new round has just been enqueued: left alone
    during = await quote_of(session, quote_id)
    api.clock.advance(RETRY_WINDOW + timedelta(seconds=1))
    await service.post(SWEEP)
    after = await quote_of(session, quote_id)

    assert during["submission"]["delivery"]["status"] == "delivering"
    assert after["submission"]["delivery"]["status"] == "abandoned"
    assert after["status"] == "approved"
    assert audit_codes(after).count("audit.delivery_abandoned") == 2
