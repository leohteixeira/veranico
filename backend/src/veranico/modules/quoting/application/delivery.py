"""Delivery bookkeeping and the outbox sweep: the system side of the facade."""

import logging
from datetime import timedelta

from veranico.modules.quoting.application.approvals import OutboxEnqueuer
from veranico.modules.quoting.application.ports import OutboxStore, QuoteRepository
from veranico.modules.quoting.contracts import DeliveryAttempt, SubmissionApproved
from veranico.modules.quoting.domain.outbox import OutboxRecord, is_silent
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId

_logger = logging.getLogger(__name__)


class DeliveryService:
    def __init__(
        self,
        *,
        quotes: QuoteRepository,
        outbox: OutboxStore,
        enqueuer: OutboxEnqueuer,
        clock: Clock,
        retry_window_seconds: int,
    ) -> None:
        self._quotes = quotes
        self._outbox = outbox
        self._enqueuer = enqueuer
        self._clock = clock
        self._retry_window_seconds = retry_window_seconds

    async def load_event(self, event_id: EventId) -> SubmissionApproved:
        record = await self._outbox.get(event_id)
        if record is None:
            raise NotFoundError
        return record.event

    async def record_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        """Idempotent per (`event_id`, `attempt`); a receipt moves the quote to `submitted`.

        The queue may keep calling after the application gave a delivery up, so an attempt
        is accepted in every delivery state and never regresses it (the aggregate decides).
        """
        at = self._clock.now()

        def mutate(quote: Quote, record: OutboxRecord) -> Mutation:
            return quote.record_attempt(record, attempt, at=at)

        await self._quotes.update_for_event(attempt.event_id, mutate)

    async def record_delivery_abandoned(self, event_id: EventId) -> None:
        at = self._clock.now()

        def mutate(quote: Quote, record: OutboxRecord) -> Mutation:
            return quote.mark_abandoned(record, at=at)

        await self._quotes.update_for_event(event_id, mutate)

    async def sweep_outbox(self, older_than_seconds: int) -> int:
        """Enqueue committed events never handed over; abandon deliveries gone silent.

        Returns the number of events enqueued. One failing record never stops the others.
        """
        now = self._clock.now()
        threshold = now - timedelta(seconds=older_than_seconds)
        enqueued = 0
        for record in await self._outbox.list_by_status("pending"):
            if record.created_at <= threshold and await self._enqueuer.enqueue(record.event_id):
                enqueued += 1

        window = self._retry_window_seconds

        def abandon_if_silent(quote: Quote, record: OutboxRecord) -> Mutation:
            # Judged again inside the transaction: an attempt may have arrived meanwhile.
            if not is_silent(record, now, window):
                return Mutation(quote)
            return quote.mark_abandoned(record, at=now)

        for record in await self._outbox.list_by_status("enqueued"):
            if not is_silent(record, now, window):
                continue
            try:
                await self._quotes.update_for_event(record.event_id, abandon_if_silent)
            except Exception:
                _logger.warning(
                    "silent delivery not abandoned; the next sweep tries again",
                    extra={"event_id": record.event_id},
                    exc_info=True,
                )
        return enqueued
