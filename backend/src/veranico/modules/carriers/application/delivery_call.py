"""One call of the queue to the internal deliver route: number the attempt, deliver, and
decide whether the queue should call again.

The queue (Cloud Tasks, or the relay in development) is the only layer that retries. It
retries on any answer outside 2xx, so the route must answer an error only for a failure
worth retrying, and must stop the queue once the round is over.
"""

import logging
from dataclasses import dataclass

from veranico.modules.carriers.contracts import CarriersFacade, DeliveryOutcome
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.shared.kernel.ids import EventId

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryCallResult:
    outcome: DeliveryOutcome
    retry: bool  # True: answer an error so the queue calls again


class DeliveryCalls:
    def __init__(
        self, *, carriers: CarriersFacade, quoting: QuotingFacade, attempt_limit: int
    ) -> None:
        self._carriers = carriers
        self._quoting = quoting
        self._attempt_limit = attempt_limit

    async def handle_delivery_call(
        self, event_id: EventId, base: int, retry_count: int
    ) -> DeliveryCallResult:
        """Perform attempt `base + retry_count + 1` of the event.

        `base` is the highest attempt number recorded before this delivery round and
        `retry_count` the queue's count of earlier dispatches in the round. The round ends
        here, with the delivery abandoned, on a failure that cannot succeed or on a failure
        at or past the last attempt of the round. The limit is checked on the position in
        the round, never on the absolute attempt number, so the first attempt of a
        redelivery is not abandoned. "At or past" matters: the queue also counts dispatches
        that never reached this route and may keep calling after the limit; such a call
        still makes its one attempt (the carrier deduplicates) and is never retried.
        """
        outcome = await self._carriers.deliver(event_id, base + retry_count + 1)
        if outcome.delivered:
            return DeliveryCallResult(outcome=outcome, retry=False)
        if outcome.retryable and retry_count + 1 < self._attempt_limit:
            return DeliveryCallResult(outcome=outcome, retry=True)
        await self._quoting.record_delivery_abandoned(event_id)
        _logger.warning(
            "webhook delivery abandoned",
            extra={
                "event_id": event_id,
                "attempt": outcome.attempt.attempt,
                "error_code": outcome.attempt.error_code,
            },
        )
        return DeliveryCallResult(outcome=outcome, retry=False)
