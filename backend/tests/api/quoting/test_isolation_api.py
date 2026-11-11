"""Workspace isolation over HTTP: for every route that takes a quote or an approval id, a
second workspace gets 404 `not_found`, the same answer as for an id that does not exist."""

import pytest

from tests.api.quoting.conftest import V1, QuotingApi, quote_body

pytestmark = [pytest.mark.integration, pytest.mark.req("R-10.1-2")]


@pytest.mark.req("R-6-3")
async def test_a_second_workspace_gets_not_found_on_every_route_with_an_id(
    api: QuotingApi,
) -> None:
    owner = await api.session()
    stranger = await api.session()
    quote = (
        await owner.api.post(
            f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-1"}
        )
    ).json()
    submission = (
        await owner.api.post(
            f"{V1}/quotes/{quote['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
        )
    ).json()
    quote_id, approval_id = quote["quote_id"], submission["submission_id"]

    responses = [
        await stranger.browser.get(f"{V1}/quotes/{quote_id}"),
        await stranger.api.get(f"{V1}/quotes/{quote_id}"),
        await stranger.browser.post(
            f"{V1}/quotes/{quote_id}/submissions", json={"carrier_id": "carrier-1"}
        ),
        await stranger.api.post(
            f"{V1}/quotes/{quote_id}/submissions", json={"carrier_id": "carrier-9"}
        ),
        await stranger.browser.post(
            f"{V1}/approvals/{approval_id}/decision", json={"approve": True}
        ),
        await stranger.browser.post(
            f"{V1}/approvals/{approval_id}/decision", json={"approve": False}
        ),
        await stranger.browser.post(f"{V1}/approvals/{approval_id}/redeliver"),
    ]
    missing = await owner.browser.get(f"{V1}/quotes/Q-MSSNG0")

    for response in responses:
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "not_found"
        # Nothing tells a foreign quote from a missing one.
        assert {k: v for k, v in body.items() if k != "trace_id"} == {
            k: v for k, v in missing.json().items() if k != "trace_id"
        }
    after = (await owner.browser.get(f"{V1}/quotes/{quote_id}")).json()
    assert after["status"] == "pending_approval"
    assert len(after["audit"]) == 2
    assert api.dispatcher.enqueued == []


async def test_lists_hold_nothing_of_another_workspace(api: QuotingApi) -> None:
    owner = await api.session()
    stranger = await api.session()
    quote = (
        await owner.api.post(
            f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-1"}
        )
    ).json()
    await owner.api.post(
        f"{V1}/quotes/{quote['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
    )

    assert (await stranger.browser.get(f"{V1}/quotes")).json() == []
    assert (await stranger.browser.get(f"{V1}/approvals")).json() == []
    assert len((await owner.browser.get(f"{V1}/quotes")).json()) == 1
    assert len((await owner.browser.get(f"{V1}/approvals")).json()) == 1


@pytest.mark.req("R-6-4")
async def test_the_same_idempotency_key_in_two_workspaces_gives_two_quotes(
    api: QuotingApi,
) -> None:
    owner = await api.session()
    stranger = await api.session()
    key = {"Idempotency-Key": "shared-key"}

    mine = await owner.api.post(f"{V1}/quotes", json=quote_body(), headers=key)
    theirs = await stranger.api.post(f"{V1}/quotes", json=quote_body(label="other"), headers=key)

    assert (mine.status_code, theirs.status_code) == (200, 200)
    assert mine.json()["quote_id"] != theirs.json()["quote_id"]
    assert theirs.json()["workspace_id"] == stranger.workspace_id
