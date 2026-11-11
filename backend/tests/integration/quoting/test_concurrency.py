"""Concurrent requests on one document. Outcomes are asserted, never timing.

The emulator does not behave as production under contention: it refuses the commit of every
contender but one after a wait of about two seconds, and the client library runs a refused
transaction again at most five times. So the contenders are few (two decisions, as in SPEC
16.3), and a loser may end in either of two ways, both a 409 for the caller and both
leaving the winner's state untouched: `invalid_state` (it ran again and saw the decision) or
`conflict` (its attempts ran out). The invariant is the same in both: exactly one outcome.

For the idempotent operations (a repeated submission request, a repeated attempt record) a
`conflict` means nothing was written and the caller may repeat: `settled` repeats such a
call a bounded number of times, as a client would, and the test then asserts that the
repetition changed nothing more.

`create_quote` uses no transaction (an atomic `create` of the key and of the quote), so
twenty contenders are fine there.
"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from google.cloud.firestore_v1.base_query import FieldFilter

from tests.integration.quoting.conftest import Env
from veranico.modules.quoting.contracts import (
    ApprovalView,
    Decision,
    DeliveryAttempt,
    Submission,
)
from veranico.modules.quoting.infrastructure.mapping import IDEMPOTENCY
from veranico.shared.kernel.errors import ConflictError, InvalidStateError

pytestmark = pytest.mark.integration

LOSER = (InvalidStateError, ConflictError)
REPEATS = 3


async def settled[T](call: Callable[[], Awaitable[T]]) -> T:
    """Run an idempotent call, repeating it when contention ran its attempts out."""
    for _ in range(REPEATS - 1):
        try:
            return await call()
        except ConflictError:
            continue
    return await call()


@pytest.mark.req("R-6-8")
@pytest.mark.req("R-6-7")
@pytest.mark.parametrize("round_number", range(3))
async def test_an_approval_and_a_rejection_started_together_leave_one_outcome(
    env: Env, round_number: int
) -> None:
    submission = await env.pending()

    results = await asyncio.gather(
        env.service.decide(env.browser, submission.submission_id, Decision(approve=True)),
        env.service.decide(env.browser, submission.submission_id, Decision(approve=False)),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, ApprovalView)]
    losers = [result for result in results if not isinstance(result, ApprovalView)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], LOSER)
    (winner,) = winners
    view = await env.view(winner.quote_id)
    decisions = [
        entry.action.code
        for entry in view.audit
        if entry.action.code in ("audit.approved", "audit.rejected")
    ]
    outbox = await env.outbox_documents()
    approved = results[0] is winner
    assert view.status == ("approved" if approved else "rejected")
    assert decisions == ["audit.approved" if approved else "audit.rejected"]
    assert len(outbox) == (1 if approved else 0)
    assert len(env.dispatcher.enqueued) == len(outbox)
    assert winner.status == ("approved" if approved else "rejected")


@pytest.mark.req("R-6-8")
async def test_two_approvals_started_together_write_one_event(env: Env) -> None:
    submission = await env.pending()

    results = await asyncio.gather(
        *(
            env.service.decide(env.browser, submission.submission_id, Decision(approve=True))
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, ApprovalView)]
    assert len(winners) == 1
    assert all(isinstance(result, LOSER) for result in results if result is not winners[0])
    assert len(await env.outbox_documents()) == 1
    assert len(env.dispatcher.enqueued) == 1
    assert (await env.audit_codes(winners[0].quote_id)).count("audit.approved") == 1


@pytest.mark.req("R-6-4")
async def test_twenty_creations_with_one_key_started_together_leave_one_quote(env: Env) -> None:
    command = env.command()

    views = await asyncio.gather(
        *(env.service.create_quote(env.api_key, command, "key-a", "api_client") for _ in range(20))
    )

    assert len({view.quote_id for view in views}) == 1
    assert all(view == views[0] for view in views)
    stored = await env.quotes.list_for_workspace(env.workspace_id)
    assert [quote.quote_id for quote in stored] == [views[0].quote_id]
    assert await env.audit_codes(views[0].quote_id) == ["audit.quote_created"]
    keys = env.client.collection(IDEMPOTENCY).where(
        filter=FieldFilter("workspace_id", "==", env.workspace_id)
    )
    assert len([key async for key in keys.stream()]) == 1


@pytest.mark.req("R-6-5")
async def test_two_submission_requests_started_together_return_one_submission(env: Env) -> None:
    quote = await env.draft()

    def request(carrier_id: str) -> Callable[[], Awaitable[Submission]]:
        return lambda: env.service.request_submission(
            env.api_key, quote.quote_id, carrier_id, "agent"
        )

    first, second = await asyncio.gather(
        settled(request("carrier-1")), settled(request("carrier-2"))
    )

    assert first == second
    view = await env.view(quote.quote_id)
    assert view.submission == first
    assert [e.action.code for e in view.audit].count("audit.submission_requested") == 1


@pytest.mark.req("R-7-4")
async def test_the_same_attempt_recorded_twice_together_is_one_audit_entry(env: Env) -> None:
    approval = await env.approved()
    attempt = DeliveryAttempt(
        event_id=await env.event_of(approval.quote_id),
        attempt=1,
        status_code=200,
        error_code=None,
        duration_ms=20,
        receipt_id="R-000001",
    )

    def record() -> Awaitable[None]:
        return env.service.record_delivery_attempt(attempt)

    await asyncio.gather(settled(record), settled(record))

    codes = await env.audit_codes(approval.quote_id)
    assert codes.count("audit.webhook_attempt") == 1
    assert codes.count("audit.receipt_recorded") == 1
    view = await env.view(approval.quote_id)
    assert view.status == "submitted"
    assert view.submission is not None
    assert view.submission.delivery.attempts == 1
