"""SPEC 16.3: concurrent `POST /quotes` with one idempotency key, through HTTP.

The invariant is the one the load oracle of SPEC 16.5 checks: one key, one quote.
"""

import asyncio

import pytest

from tests.api.quoting.conftest import V1, QuotingApi, quote_body
from tests.failure.quoting.conftest import audit_codes, quote_of, stored_keys, stored_quotes

pytestmark = [
    pytest.mark.failure,
    pytest.mark.integration,
    pytest.mark.req("R-16.3-6"),
    pytest.mark.req("R-6-4"),
]


@pytest.mark.parametrize("contenders", [2, 20])
async def test_concurrent_creations_with_one_key_leave_one_quote(
    api: QuotingApi, contenders: int
) -> None:
    session = await api.session()
    key = {"Idempotency-Key": "shared-request"}

    responses = await asyncio.gather(
        *(
            session.api.post(f"{V1}/quotes", json=quote_body(), headers=key)
            for _ in range(contenders)
        )
    )

    assert [response.status_code for response in responses] == [200] * contenders
    bodies = [response.json() for response in responses]
    assert len({body["quote_id"] for body in bodies}) == 1
    assert all(body == bodies[0] for body in bodies)
    assert await stored_quotes(api, session.workspace_id) == [bodies[0]["quote_id"]]
    assert len(await stored_keys(api, session.workspace_id)) == 1
    quote = await quote_of(session, bodies[0]["quote_id"])
    assert audit_codes(quote) == ["audit.quote_created"]

    another = await session.api.post(
        f"{V1}/quotes", json=quote_body(label="another payload"), headers=key
    )
    assert (another.status_code, another.json()["code"]) == (409, "idempotency_conflict")
