from datetime import timedelta

import pytest

from tests.api.quoting.conftest import INTERNAL_TOKEN, V1, QuotingApi, quote_body

pytestmark = [pytest.mark.integration, pytest.mark.req("R-11.3-2")]

SWEEP = f"{V1}/internal/outbox/sweep"
SERVICE = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}


async def test_the_sweep_route_accepts_only_the_service_identity(api: QuotingApi) -> None:
    session = await api.session()

    anonymous = await api.client().post(SWEEP)
    wrong = await api.client({"Authorization": "Bearer not-the-token"}).post(SWEEP)
    by_cookie = await session.browser.post(SWEEP)
    by_api_key = await session.api.post(SWEEP)

    for response in (anonymous, wrong, by_cookie, by_api_key):
        assert (response.status_code, response.json()["code"]) == (403, "forbidden")


@pytest.mark.req("R-7-5")
async def test_the_sweep_enqueues_a_committed_event_that_was_never_enqueued(
    api: QuotingApi,
) -> None:
    session = await api.session()
    quote = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-1"}
    )
    submission = await session.api.post(
        f"{V1}/quotes/{quote.json()['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
    )
    api.dispatcher.failure = RuntimeError("queue unavailable")
    decided = await session.browser.post(
        f"{V1}/approvals/{submission.json()['submission_id']}/decision", json={"approve": True}
    )
    api.dispatcher.failure = None
    service = api.client(SERVICE)

    too_early = await service.post(SWEEP)
    api.clock.advance(timedelta(seconds=60))  # the default sweep age
    swept = await service.post(SWEEP)
    again = await service.post(SWEEP)

    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert too_early.status_code == 200
    assert too_early.json().keys() == {"enqueued"}
    assert swept.status_code == 200
    # The outbox is shared with other runs on the emulator, so the count is a lower bound
    # here; this run's event is enqueued exactly once.
    assert swept.json()["enqueued"] >= 1
    assert again.status_code == 200
    assert len(api.dispatcher.enqueued) == 1
    event = await api.facade.load_event(api.dispatcher.enqueued[0])
    assert event.data.submission_id == submission.json()["submission_id"]
