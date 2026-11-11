from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.api.quoting.conftest import V1, QuotingApi, Session, quote_body

pytestmark = pytest.mark.integration


async def _pending(session: Session, key: str = "request-1") -> dict[str, Any]:
    """A quote with a requested submission; returns the submission."""
    quote = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": key}
    )
    submission = await session.api.post(
        f"{V1}/quotes/{quote.json()['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
    )
    assert submission.status_code == 200
    return {**submission.json(), "quote_id": quote.json()["quote_id"]}


async def _decide(
    session: Session, approval_id: str, approve: bool, note: str | None = None
) -> httpx.Response:
    return await session.browser.post(
        f"{V1}/approvals/{approval_id}/decision", json={"approve": approve, "note": note}
    )


@pytest.mark.req("R-6-3")
@pytest.mark.req("R-6-7")
@pytest.mark.req("R-10.1-4")
@pytest.mark.req("R-11.2-6")
async def test_an_approval_from_the_browser_session_approves_and_enqueues(
    api: QuotingApi,
) -> None:
    session = await api.session()
    pending = await _pending(session)
    api.clock.advance(timedelta(minutes=5))

    response = await _decide(session, pending["submission_id"], True, "go ahead")

    assert response.status_code == 200
    approval = response.json()
    assert approval["approval_id"] == pending["submission_id"]
    assert approval["quote_id"] == pending["quote_id"]
    assert approval["status"] == "approved"
    assert (approval["carrier_id"], approval["carrier_name"]) == ("carrier-1", "Fake Carrier One")
    assert approval["delivery"] == {
        "status": "delivering",
        "attempts": 0,
        "receipt_id": None,
        "last_error_code": None,
    }
    quote = (await session.browser.get(f"{V1}/quotes/{pending['quote_id']}")).json()
    assert quote["status"] == "approved"
    assert quote["submission"]["decision_note"] == "go ahead"
    decision = quote["audit"][-1]
    assert (decision["actor"], decision["action"]["code"]) == ("human", "audit.approved")
    assert decision["note"] == "go ahead"
    assert len(api.dispatcher.enqueued) == 1
    event = await api.facade.load_event(api.dispatcher.enqueued[0])
    assert event.data.submission_id == pending["submission_id"]
    assert event.data.premium.amount_cents == approval["premium"]["amount_cents"]


@pytest.mark.req("R-10.1-4")
@pytest.mark.req("R-11.2-6")
async def test_a_rejection_decides_without_enqueueing(api: QuotingApi) -> None:
    session = await api.session()
    pending = await _pending(session)

    response = await _decide(session, pending["submission_id"], False, "too risky")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["delivery"]["status"] == "not_started"
    quote = (await session.browser.get(f"{V1}/quotes/{pending['quote_id']}")).json()
    assert quote["status"] == "rejected"
    assert (quote["audit"][-1]["action"]["code"], quote["audit"][-1]["note"]) == (
        "audit.rejected",
        "too risky",
    )
    assert api.dispatcher.enqueued == []


@pytest.mark.req("R-6-8")
async def test_a_second_decision_is_an_invalid_state(api: QuotingApi) -> None:
    session = await api.session()
    pending = await _pending(session)
    await _decide(session, pending["submission_id"], True)

    for approve in (True, False):
        again = await _decide(session, pending["submission_id"], approve)
        assert (again.status_code, again.json()["code"]) == (409, "invalid_state")

    quote = (await session.browser.get(f"{V1}/quotes/{pending['quote_id']}")).json()
    assert quote["status"] == "approved"
    assert [e["action"]["code"] for e in quote["audit"]].count("audit.approved") == 1
    assert len(api.dispatcher.enqueued) == 1


@pytest.mark.req("R-6-3")
async def test_an_api_key_cannot_decide(api: QuotingApi) -> None:
    """The decision route reads only the cookie: a bearer alone is a browser with no
    workspace of its own yet, so the approval of the key's workspace does not exist for it."""
    session = await api.session()
    pending = await _pending(session)
    key_only = api.client({"Authorization": session.api.headers["Authorization"]})

    for approve in (True, False):
        response = await key_only.post(
            f"{V1}/approvals/{pending['submission_id']}/decision", json={"approve": approve}
        )
        assert (response.status_code, response.json()["code"]) == (404, "not_found")

    quote = (await session.api.get(f"{V1}/quotes/{pending['quote_id']}")).json()
    assert quote["status"] == "pending_approval"
    assert api.dispatcher.enqueued == []


async def test_a_note_over_500_characters_is_refused(api: QuotingApi) -> None:
    session = await api.session()
    pending = await _pending(session)

    too_long = await _decide(session, pending["submission_id"], True, "n" * 501)
    accepted = await _decide(session, pending["submission_id"], True, "n" * 500)

    assert (too_long.status_code, too_long.json()["code"]) == (422, "invalid_arguments")
    assert accepted.status_code == 200


@pytest.mark.req("R-11.2-5")
async def test_the_queue_is_filtered_by_status(api: QuotingApi) -> None:
    session = await api.session()
    pending = await _pending(session, "request-1")
    api.clock.advance(timedelta(minutes=1))
    approved = await _pending(session, "request-2")
    await _decide(session, approved["submission_id"], True)
    api.clock.advance(timedelta(minutes=1))
    rejected = await _pending(session, "request-3")
    await _decide(session, rejected["submission_id"], False)

    async def ids(query: str) -> list[str]:
        response = await session.browser.get(f"{V1}/approvals{query}")
        assert response.status_code == 200
        return [approval["approval_id"] for approval in response.json()]

    assert await ids("?status=pending") == [pending["submission_id"]]
    assert await ids("?status=approved") == [approved["submission_id"]]
    assert await ids("?status=rejected") == [rejected["submission_id"]]
    assert await ids("") == [
        rejected["submission_id"],
        approved["submission_id"],
        pending["submission_id"],
    ]
    unknown = await session.browser.get(f"{V1}/approvals?status=submitted")
    assert (unknown.status_code, unknown.json()["code"]) == (422, "invalid_arguments")


@pytest.mark.req("R-7-6")
@pytest.mark.req("R-11.2-7")
async def test_a_redelivery_is_refused_before_an_abandonment_and_accepted_after(
    api: QuotingApi,
) -> None:
    session = await api.session()
    pending = await _pending(session)
    redeliver = f"{V1}/approvals/{pending['submission_id']}/redeliver"

    before_decision = await session.browser.post(redeliver)
    await _decide(session, pending["submission_id"], True)
    while_delivering = await session.browser.post(redeliver)

    for response in (before_decision, while_delivering):
        assert (response.status_code, response.json()["code"]) == (409, "invalid_state")

    (event_id,) = api.dispatcher.enqueued
    await api.facade.record_delivery_abandoned(event_id)
    queue = (await session.browser.get(f"{V1}/approvals?status=approved")).json()
    assert [approval["delivery"]["status"] for approval in queue] == ["abandoned"]

    after = await session.browser.post(redeliver)

    assert after.status_code == 200
    assert (after.json()["status"], after.json()["delivery"]["status"]) == (
        "approved",
        "delivering",
    )
    assert api.dispatcher.enqueued == [event_id, event_id]
    quote = (await session.browser.get(f"{V1}/quotes/{pending['quote_id']}")).json()
    assert [(e["actor"], e["action"]["code"]) for e in quote["audit"]][-2:] == [
        ("system", "audit.delivery_abandoned"),
        ("human", "audit.redelivery_requested"),
    ]
