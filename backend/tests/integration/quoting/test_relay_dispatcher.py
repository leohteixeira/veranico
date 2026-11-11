"""The relay on the Firestore emulator, with a mock transport playing the deliver endpoint.

The endpoint does what the deliver route of `carriers` does: it numbers the attempt from the
two headers (`base + retry count + 1`) and records the result through `QuotingService`.

The relay lists the whole outbox by status and the emulator is shared, so here it reads
through `ScopedOutbox`, which lists only the records of the test's own workspace: the
records of other runs are never called or changed by these tests.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import httpx
import pytest

from tests.integration.quoting.conftest import RETRY_WINDOW_SECONDS, SWEEP_AGE_SECONDS, Env
from tests.unit.quoting.world import FixedCatalog
from veranico.modules.quoting.application.facade import QuotingService
from veranico.modules.quoting.contracts import ApprovalView, Decision, DeliveryAttempt
from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus
from veranico.modules.quoting.infrastructure.firestore_outbox import FirestoreOutboxStore
from veranico.modules.quoting.infrastructure.relay_dispatcher import RelayDispatcher
from veranico.shared.kernel.ids import EventId, QuoteId, WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.req("R-7-11")]

BASE_URL = "http://api.internal.test"
TOKEN = "test-internal-token"  # a fixed test string, not a secret
ATTEMPT_LIMIT = 3
Answer = Literal["receipt", "fail", "unreachable", "hang"]


class ScopedOutbox:
    """The outbox store, listing only the records of one workspace."""

    def __init__(self, store: FirestoreOutboxStore, workspace_id: WorkspaceId) -> None:
        self._store = store
        self._workspace_id = workspace_id

    async def get(self, event_id: EventId) -> OutboxRecord | None:
        return await self._store.get(event_id)

    async def list_by_status(self, status: OutboxStatus) -> list[OutboxRecord]:
        return [
            record
            for record in await self._store.list_by_status(status)
            if record.event.workspace_id == self._workspace_id
        ]

    async def mark_enqueued(self, event_id: EventId, at: datetime) -> None:
        await self._store.mark_enqueued(event_id, at)

    async def record_dispatch(self, event_id: EventId, next_attempt_at: datetime) -> None:
        await self._store.record_dispatch(event_id, next_attempt_at)


@dataclass(frozen=True)
class Call:
    event_id: str
    base: int
    retry_count: int
    authorization: str | None
    body: bytes


class DeliverEndpoint:
    """Plays `POST /api/v1/internal/outbox/{event_id}/deliver`; `answers` scripts the calls."""

    def __init__(self) -> None:
        self.service: QuotingService | None = None
        self.answers: list[Answer] = []
        self.calls: list[Call] = []
        self.entered = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        assert self.service is not None
        prefix, suffix = "/api/v1/internal/outbox/", "/deliver"
        assert request.method == "POST"
        assert request.url.path.startswith(prefix)
        assert request.url.path.endswith(suffix)
        event_id = EventId(request.url.path.removeprefix(prefix).removesuffix(suffix))
        base = int(request.headers["Veranico-Attempt-Base"])
        retry_count = int(request.headers["X-CloudTasks-TaskRetryCount"])
        self.calls.append(
            Call(event_id, base, retry_count, request.headers.get("Authorization"), request.content)
        )
        answer = self.answers.pop(0) if self.answers else "receipt"
        self.entered.set()
        if answer == "hang":
            await asyncio.Event().wait()
        if answer == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        attempt = DeliveryAttempt(
            event_id=event_id,
            attempt=base + retry_count + 1,
            status_code=200 if answer == "receipt" else 503,
            error_code=None if answer == "receipt" else "delivery_failed",
            duration_ms=5,
            receipt_id="R-000001" if answer == "receipt" else None,
        )
        await self.service.record_delivery_attempt(attempt)
        if answer == "receipt":
            return httpx.Response(200)
        if retry_count + 1 < ATTEMPT_LIMIT:
            return httpx.Response(503)
        await self.service.record_delivery_abandoned(event_id)
        return httpx.Response(200)


@dataclass
class Relayed:
    env: Env
    endpoint: DeliverEndpoint
    http: httpx.AsyncClient
    relay: RelayDispatcher
    service: QuotingService

    def new_relay(self) -> RelayDispatcher:
        return _relay(self.env, self.http)

    async def approve(self) -> ApprovalView:
        submission = await self.env.pending()
        return await self.service.decide(
            self.env.browser, submission.submission_id, Decision(approve=True)
        )

    async def until(self, quote_id: QuoteId, status: OutboxStatus) -> None:
        """Wait, for a bounded time, until the outbox record of the quote has the status."""
        for _ in range(400):
            record = await self.env.record_of(quote_id)
            if record.status == status:
                return
            await asyncio.sleep(0.02)
        pytest.fail(f"the record of {quote_id} never became {status}")


def _relay(env: Env, http: httpx.AsyncClient) -> RelayDispatcher:
    return RelayDispatcher(
        outbox=ScopedOutbox(env.outbox, env.workspace_id),
        http=http,
        clock=env.clock,
        base_url=BASE_URL,
        internal_token=TOKEN,
        poll_interval_seconds=0.02,
        backoff_base_seconds=1.0,
        backoff_cap_seconds=4.0,
        call_timeout_seconds=5.0,
        jitter=lambda _low, high: high,  # the upper bound: delays are exact in the tests
    )


@pytest.fixture
async def relayed(env: Env) -> AsyncIterator[Relayed]:
    endpoint = DeliverEndpoint()
    http = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    relay = _relay(env, http)
    service = QuotingService(
        quotes=env.quotes,
        idempotency=env.idempotency,
        outbox=env.outbox,
        climate=env.climate,
        pricing=env.pricing,
        carriers=FixedCatalog(),
        dispatcher=relay,
        clock=env.clock,
        sweep_age_seconds=SWEEP_AGE_SECONDS,
        retry_window_seconds=RETRY_WINDOW_SECONDS,
    )
    endpoint.service = service
    yield Relayed(env, endpoint, http, relay, service)
    await relay.stop()
    await http.aclose()


async def test_an_approved_event_is_delivered_without_any_sweep(relayed: Relayed) -> None:
    await relayed.relay.start()

    approval = await relayed.approve()
    await relayed.until(approval.quote_id, "delivered")

    (call,) = relayed.endpoint.calls
    assert call == Call(
        event_id=await relayed.env.event_of(approval.quote_id),
        base=0,
        retry_count=0,
        authorization=f"Bearer {TOKEN}",
        body=b"",
    )
    view = await relayed.env.view(approval.quote_id)
    assert view.status == "submitted"
    assert view.submission is not None
    assert view.submission.delivery.receipt_id == "R-000001"
    assert [entry.action.code for entry in view.audit][-2:] == [
        "audit.webhook_attempt",
        "audit.receipt_recorded",
    ]


@pytest.mark.req("R-7-5")
async def test_a_record_left_pending_before_the_relay_starts_is_delivered_after_start(
    relayed: Relayed,
) -> None:
    """A restart: the approval committed, the process died, nothing is in memory."""
    approval = await relayed.env.never_enqueued()
    assert (await relayed.env.record_of(approval.quote_id)).status == "pending"

    await relayed.relay.start()
    await relayed.until(approval.quote_id, "delivered")

    assert len(relayed.endpoint.calls) == 1
    assert (await relayed.env.view(approval.quote_id)).status == "submitted"
    record = await relayed.env.record_of(approval.quote_id)
    assert record.enqueued_at == relayed.env.start  # picked up by the relay, as a queue would


async def test_a_failing_endpoint_is_called_again_only_after_the_stored_delay(
    relayed: Relayed,
) -> None:
    env, relay, endpoint = relayed.env, relayed.relay, relayed.endpoint
    endpoint.answers = ["fail", "unreachable", "receipt"]
    approval = await relayed.approve()  # the relay is not started: ticks are run by hand

    assert await relay.run_once() == 1
    first = await env.record_of(approval.quote_id)
    assert await relay.run_once() == 0  # not due yet
    env.clock.advance(timedelta(seconds=1) - timedelta(microseconds=1))
    assert await relay.run_once() == 0

    assert (first.status, first.dispatch_count) == ("enqueued", 1)
    assert first.next_attempt_at == env.start + timedelta(seconds=1)  # base * 2**0

    env.clock.advance(timedelta(microseconds=1))
    assert await relay.run_once() == 1  # the endpoint cannot be reached this time
    second = await env.record_of(approval.quote_id)
    assert (second.dispatch_count, second.recorded_attempts) == (2, (1,))
    assert second.next_attempt_at == env.clock.now() + timedelta(seconds=2)  # base * 2**1
    assert await relay.run_once() == 0

    env.clock.advance(timedelta(seconds=2))
    assert await relay.run_once() == 1

    assert [(call.base, call.retry_count) for call in endpoint.calls] == [(0, 0), (0, 1), (0, 2)]
    view = await env.view(approval.quote_id)
    assert view.status == "submitted"
    assert view.submission is not None
    # The unreachable call recorded nothing, as a queue dispatch that never arrived.
    assert view.submission.delivery.attempts == 2
    assert (await env.record_of(approval.quote_id)).recorded_attempts == (1, 3)


async def test_the_delay_is_capped(relayed: Relayed) -> None:
    env, relay, endpoint = relayed.env, relayed.relay, relayed.endpoint
    endpoint.answers = ["unreachable"] * 4
    approval = await relayed.approve()
    delays = []

    for _ in range(4):
        assert await relay.run_once() == 1
        record = await env.record_of(approval.quote_id)
        assert record.next_attempt_at is not None
        delays.append((record.next_attempt_at - env.clock.now()).total_seconds())
        env.clock.advance(timedelta(seconds=delays[-1]))

    assert delays == [1.0, 2.0, 4.0, 4.0]
    assert (await env.record_of(approval.quote_id)).recorded_attempts == ()


@pytest.mark.req("R-7-6")
async def test_a_delivered_or_abandoned_record_is_never_called_again(relayed: Relayed) -> None:
    env, relay, endpoint = relayed.env, relayed.relay, relayed.endpoint
    delivered = await relayed.approve()
    assert await relay.run_once() == 1
    endpoint.answers = ["fail"] * ATTEMPT_LIMIT
    abandoned = await relayed.approve()
    for _ in range(ATTEMPT_LIMIT):
        assert await relay.run_once() == 1
        env.clock.advance(timedelta(seconds=10))
    calls = len(endpoint.calls)

    env.clock.advance(timedelta(days=1))
    assert await relay.run_once() == 0

    assert len(endpoint.calls) == calls == 1 + ATTEMPT_LIMIT
    assert (await env.record_of(delivered.quote_id)).status == "delivered"
    record = await env.record_of(abandoned.quote_id)
    assert (record.status, record.recorded_attempts) == ("abandoned", (1, 2, 3))
    view = await env.view(abandoned.quote_id)
    assert view.status == "approved"
    assert view.submission is not None
    assert view.submission.delivery.status == "abandoned"

    # A manual redelivery opens a new round: the base continues, the retry count restarts.
    await relayed.service.redeliver(env.browser, abandoned.approval_id)
    assert await relay.run_once() == 1

    last = endpoint.calls[-1]
    assert (last.base, last.retry_count) == (3, 0)
    assert (await env.view(abandoned.quote_id)).status == "submitted"
    assert (await env.record_of(abandoned.quote_id)).recorded_attempts == (1, 2, 3, 4)


async def test_a_relay_stopped_in_the_middle_of_a_call_leaves_the_record_deliverable(
    relayed: Relayed,
) -> None:
    env, endpoint = relayed.env, relayed.endpoint
    endpoint.answers = ["hang"]
    await relayed.relay.start()
    approval = await relayed.approve()
    await asyncio.wait_for(endpoint.entered.wait(), timeout=8)

    await relayed.relay.stop()

    record = await env.record_of(approval.quote_id)
    assert (record.status, record.dispatch_count, record.next_attempt_at) == ("enqueued", 0, None)
    assert record.recorded_attempts == ()

    successor = relayed.new_relay()
    await successor.start()
    try:
        await relayed.until(approval.quote_id, "delivered")
    finally:
        await successor.stop()

    assert [(call.base, call.retry_count) for call in endpoint.calls] == [(0, 0), (0, 0)]
    assert (await env.view(approval.quote_id)).status == "submitted"


async def test_start_and_stop_are_safe_to_repeat_and_enqueue_never_calls_by_itself(
    relayed: Relayed,
) -> None:
    approval = await relayed.env.never_enqueued()
    event_id = await relayed.env.event_of(approval.quote_id)

    await relayed.relay.stop()  # never started
    await relayed.relay.enqueue(event_id)  # only wakes a loop; none is running

    assert relayed.endpoint.calls == []

    await relayed.relay.start()
    await relayed.relay.start()
    await relayed.until(approval.quote_id, "delivered")
    await relayed.relay.stop()
    await relayed.relay.stop()

    assert len(relayed.endpoint.calls) == 1
