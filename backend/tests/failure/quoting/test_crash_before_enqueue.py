"""SPEC 16.3: the process dies between the commit of an approval and its enqueue.

The decision and its outbox record are one commit, so the event is never lost: the sweep
(the route, or the one `GET /approvals` runs) hands it to the queue later, exactly once.
"""

import asyncio
from datetime import timedelta

import pytest

from tests.api.quoting.conftest import QuotingApi
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
from veranico.shared.kernel.ids import EventId

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-16.3-2")]

SWEEP_AGE = timedelta(seconds=60)  # the default `delivery.sweep_age_seconds`


@pytest.mark.req("R-7-5")
async def test_an_enqueue_that_raises_after_the_commit_is_recovered_by_the_sweep_route(
    api: QuotingApi,
) -> None:
    session = await api.session()
    quote_id, approval_id = await pending(session)
    api.dispatcher.failure = RuntimeError("queue unavailable")

    decided = await decide(session, approval_id, True)

    api.dispatcher.failure = None
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["delivery"]["status"] == "delivering"
    assert await outbox_statuses(api, quote_id) == ["pending"]
    assert api.dispatcher.enqueued == []

    service = api.client(SERVICE)
    api.clock.advance(SWEEP_AGE)
    first = await service.post(SWEEP)
    second = await service.post(SWEEP)

    assert (first.status_code, first.json()) == (200, {"enqueued": 1})
    assert (second.status_code, second.json()) == (200, {"enqueued": 0})
    assert len(api.dispatcher.enqueued) == 1
    assert await outbox_statuses(api, quote_id) == ["enqueued"]
    event = await api.facade.load_event(api.dispatcher.enqueued[0])
    assert event.data.submission_id == approval_id
    quote = await quote_of(session, quote_id)
    assert quote["status"] == "approved"
    assert audit_codes(quote).count("audit.approved") == 1


@pytest.mark.req("R-7-5")
async def test_the_same_recovery_happens_through_the_approval_queue_alone(
    api: QuotingApi,
) -> None:
    session = await api.session()
    quote_id, approval_id = await pending(session)
    api.dispatcher.failure = RuntimeError("queue unavailable")
    decided = await decide(session, approval_id, True)
    api.dispatcher.failure = None

    too_early = await approval_of(session, approval_id)
    assert api.dispatcher.enqueued == []
    api.clock.advance(SWEEP_AGE)
    first = await approval_of(session, approval_id)
    second = await approval_of(session, approval_id)

    assert decided.status_code == 200
    assert [a["status"] for a in (too_early, first, second)] == ["approved"] * 3
    assert len(api.dispatcher.enqueued) == 1
    assert await outbox_statuses(api, quote_id) == ["enqueued"]


async def test_a_request_cancelled_between_commit_and_enqueue_is_recovered(
    api: QuotingApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process is killed, not failed: nothing after the commit runs, not even the
    handling of an enqueue error."""
    session = await api.session()
    quote_id, approval_id = await pending(session)
    reached = asyncio.Event()

    async def never_returns(event_id: EventId) -> None:
        reached.set()
        await asyncio.Event().wait()

    with monkeypatch.context() as patched:
        patched.setattr(api.dispatcher, "enqueue", never_returns)
        request = asyncio.create_task(decide(session, approval_id, True))
        await asyncio.wait_for(reached.wait(), timeout=30)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    quote = await quote_of(session, quote_id)
    assert quote["status"] == "approved"
    assert audit_codes(quote).count("audit.approved") == 1
    assert await outbox_statuses(api, quote_id) == ["pending"]
    assert api.dispatcher.enqueued == []

    api.clock.advance(SWEEP_AGE)
    service = api.client(SERVICE)
    first = await service.post(SWEEP)
    second = await service.post(SWEEP)

    assert (first.json(), second.json()) == ({"enqueued": 1}, {"enqueued": 0})
    assert len(api.dispatcher.enqueued) == 1
    assert await outbox_statuses(api, quote_id) == ["enqueued"]
    again = await decide(session, approval_id, True)
    assert (again.status_code, again.json()["code"]) == (409, "invalid_state")
