"""SPEC 16.3: two decisions on one approval at the same time, through HTTP.

Exactly one wins. The loser answers 409: `invalid_state` when it ran again and saw the
decision, or `conflict` when the contention ran its transaction attempts out (the emulator
refuses every contender but one after a wait; see `tests/integration/quoting`). In both
cases it wrote nothing.
"""

import asyncio

import pytest

from tests.api.quoting.conftest import QuotingApi, Session
from tests.failure.quoting.conftest import (
    DECISIONS,
    audit_codes,
    decide,
    outbox_statuses,
    pending,
    quote_of,
)

pytestmark = [
    pytest.mark.failure,
    pytest.mark.integration,
    pytest.mark.req("R-16.3-5"),
    pytest.mark.req("R-6-8"),
]

ROUNDS = 20


async def _round(api: QuotingApi, session: Session, number: int) -> None:
    quote_id, approval_id = await pending(session, f"request-{number}")
    # Odd rounds race an approval against a rejection, even rounds two approvals.
    second_approves = number % 2 == 0

    responses = await asyncio.gather(
        decide(session, approval_id, True), decide(session, approval_id, second_approves)
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    winner, loser = sorted(responses, key=lambda response: response.status_code)
    assert loser.json()["code"] in ("invalid_state", "conflict")
    approved = winner.json()["status"] == "approved"
    assert approved == (winner is responses[0] or second_approves)
    quote = await quote_of(session, quote_id)
    assert quote["status"] == ("approved" if approved else "rejected")
    assert [code for code in audit_codes(quote) if code in DECISIONS] == [
        "audit.approved" if approved else "audit.rejected"
    ]
    assert len(await outbox_statuses(api, quote_id)) == (1 if approved else 0)


async def test_two_concurrent_decisions_leave_one_outcome_twenty_times(api: QuotingApi) -> None:
    session = await api.session()

    # The rounds are on different quotes, so they do not contend with each other.
    await asyncio.gather(*(_round(api, session, number) for number in range(ROUNDS)))

    approvals = (await session.browser.get("/api/v1/approvals")).json()
    assert len(approvals) == ROUNDS
    assert all(approval["status"] in ("approved", "rejected") for approval in approvals)
    approved = [a for a in approvals if a["status"] == "approved"]
    assert len(api.dispatcher.enqueued) == len(set(api.dispatcher.enqueued)) == len(approved)
