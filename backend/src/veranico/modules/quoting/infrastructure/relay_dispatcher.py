"""`OutboxDispatcher` for development and tests: the local stand-in for Cloud Tasks.

A loop inside the API process polls `quoting_outbox` and makes the same HTTP call Cloud
Tasks would make, against the service's own base URL, so the deliver route and its
authentication are exercised without a queue. Everything the loop knows is in the outbox
record (status, calls made in the round, when the next call is due): a restart loses
nothing, and a record left `pending` by a crash is picked up like any other.

The answer of the deliver route is not interpreted. After a call the record is read again:
it is `delivered` or `abandoned`, or it is still open and the next call is scheduled with
capped exponential backoff and full jitter. The application lifespan calls `start()` and
`stop()`.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Callable
from datetime import timedelta

import httpx

from veranico.modules.quoting.application.ports import OutboxStore
from veranico.modules.quoting.domain.outbox import OutboxRecord, next_delay
from veranico.modules.quoting.infrastructure.deliver_call import (
    ATTEMPT_BASE_HEADER,
    RETRY_COUNT_HEADER,
    deliver_url,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import EventId

_logger = logging.getLogger(__name__)


class RelayDispatcher:
    def __init__(
        self,
        *,
        outbox: OutboxStore,
        http: httpx.AsyncClient,
        clock: Clock,
        base_url: str,
        internal_token: str | None,
        poll_interval_seconds: float,
        backoff_base_seconds: float,
        backoff_cap_seconds: float,
        call_timeout_seconds: float,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._outbox = outbox
        self._http = http
        self._clock = clock
        self._base_url = base_url
        self._internal_token = internal_token
        self._poll_interval = poll_interval_seconds
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds
        self._call_timeout = call_timeout_seconds
        self._jitter = jitter
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def enqueue(self, event_id: EventId) -> None:
        """Only wake the loop: the event is already in the outbox, which is the queue."""
        self._wake.set()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="quoting-outbox-relay")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def run_once(self) -> int:
        """Call the deliver endpoint for every open record that is due; return the calls."""
        now = self._clock.now()
        # By event id: a record that changes status between the two queries is listed twice.
        listed = {
            record.event_id
            for status in ("pending", "enqueued")
            for record in await self._outbox.list_by_status(status)
            if record.due(now)
        }
        calls = 0
        for event_id in sorted(listed):
            try:
                # Read again: the listing may be stale by the time this record's turn comes.
                record = await self._outbox.get(event_id)
                if record is not None and record.due(now):
                    await self._deliver(record)
                    calls += 1
            except Exception:
                # One record never stops the others; it is still due on the next tick.
                _logger.warning(
                    "outbox relay could not process a record",
                    extra={"event_id": event_id},
                    exc_info=True,
                )
        return calls

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                # The loop outlives any failure: the records are still there on the next tick.
                _logger.warning("outbox relay tick failed", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
            self._wake.clear()

    async def _deliver(self, record: OutboxRecord) -> None:
        event_id = record.event_id
        # Picked up by the queue: from here the sweep's silence rule watches the delivery.
        await self._outbox.mark_enqueued(event_id, self._clock.now())
        headers = {
            ATTEMPT_BASE_HEADER: str(record.attempt_base),
            RETRY_COUNT_HEADER: str(record.dispatch_count),
        }
        if self._internal_token is not None:
            headers["Authorization"] = f"Bearer {self._internal_token}"
        try:
            response = await self._http.post(
                deliver_url(self._base_url, event_id), headers=headers, timeout=self._call_timeout
            )
            status_code: int | None = response.status_code
        except httpx.HTTPError:
            status_code = None
        # Whatever the answer was, the record is the only truth about the delivery.
        delay = next_delay(
            record.dispatch_count, self._backoff_base, self._backoff_cap, self._jitter
        )
        await self._outbox.record_dispatch(event_id, self._clock.now() + timedelta(seconds=delay))
        _logger.info(
            "outbox relay called the deliver endpoint",
            extra={
                "event_id": event_id,
                "retry_count": record.dispatch_count,
                "status_code": status_code,
            },
        )
