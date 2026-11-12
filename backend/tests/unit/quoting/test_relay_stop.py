"""`RelayDispatcher.stop` ends the loop, never hangs and never swallows its caller's cancel."""

import asyncio
import logging

import httpx
import pytest

from tests.unit.quoting.memory import MemoryOutboxStore
from tests.unit.quoting.world import NOW
from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus
from veranico.modules.quoting.infrastructure import relay_dispatcher
from veranico.modules.quoting.infrastructure.relay_dispatcher import RelayDispatcher
from veranico.shared.kernel.clock import FixedClock


class BlockingOutbox(MemoryOutboxStore):
    """Every listing waits forever. With `swallow`, the first cancellation of a listing
    comes out as an ordinary error, as the Firestore library's failed rollback made it do;
    later ones are cancellations, so the test can still end the loop."""

    def __init__(self, *, swallow: bool) -> None:
        super().__init__()
        self.swallow = swallow
        self.listing = asyncio.Event()

    async def list_by_status(self, status: OutboxStatus) -> list[OutboxRecord]:
        self.listing.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if self.swallow:
                self.swallow = False
                raise RuntimeError("cannot roll back") from None
            raise
        return []


def _never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError("the relay has nothing to deliver")


def _relay(outbox: MemoryOutboxStore, http: httpx.AsyncClient) -> RelayDispatcher:
    return RelayDispatcher(
        outbox=outbox,
        http=http,
        clock=FixedClock(NOW),
        base_url="http://api.internal.test",
        internal_token=None,
        poll_interval_seconds=0.01,
        backoff_base_seconds=1.0,
        backoff_cap_seconds=4.0,
        call_timeout_seconds=5.0,
    )


@pytest.fixture
async def http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_never_called))


async def test_stop_cancels_a_loop_waiting_on_the_outbox(http: httpx.AsyncClient) -> None:
    outbox = BlockingOutbox(swallow=False)
    relay = _relay(outbox, http)
    await relay.start()
    await asyncio.wait_for(outbox.listing.wait(), timeout=5)
    (loop,) = [task for task in asyncio.all_tasks() if task.get_name() == "quoting-outbox-relay"]

    await asyncio.wait_for(relay.stop(), timeout=5)

    assert loop.cancelled()


async def test_stop_returns_in_bounded_time_when_the_loop_swallows_its_cancellation(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(relay_dispatcher, "STOP_TIMEOUT_SECONDS", 0.1)
    outbox = BlockingOutbox(swallow=True)
    relay = _relay(outbox, http)
    await relay.start()
    await asyncio.wait_for(outbox.listing.wait(), timeout=5)
    (loop,) = [task for task in asyncio.all_tasks() if task.get_name() == "quoting-outbox-relay"]

    with caplog.at_level(logging.WARNING, logger=relay_dispatcher.__name__):
        await asyncio.wait_for(relay.stop(), timeout=5)

    assert "outbox relay did not stop in time" in caplog.messages
    assert not loop.done()  # the defect this guards against: the loop outlives its cancel
    loop.cancel()  # a second cancellation reaches it; the test leaves nothing running
    await asyncio.wait({loop}, timeout=5)
    assert loop.done()


async def test_a_cancelled_caller_of_stop_is_not_swallowed(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown (SIGINT) cancels the task that is stopping the relay: it must end too."""
    monkeypatch.setattr(relay_dispatcher, "STOP_TIMEOUT_SECONDS", 30.0)
    outbox = BlockingOutbox(swallow=True)  # a loop that does not end on the first cancel
    relay = _relay(outbox, http)
    await relay.start()
    await asyncio.wait_for(outbox.listing.wait(), timeout=5)
    (loop,) = [task for task in asyncio.all_tasks() if task.get_name() == "quoting-outbox-relay"]
    stopping = asyncio.create_task(relay.stop())
    await asyncio.sleep(0.05)  # let `stop` cancel the loop and start waiting for it

    stopping.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopping, timeout=5)
    loop.cancel()
    await asyncio.wait({loop}, timeout=5)
