"""The outbox record of a `SubmissionApproved` event and the pure timing rules of its delivery."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from veranico.modules.quoting.contracts import SubmissionApproved
from veranico.shared.kernel.ids import EventId, QuoteId

OutboxStatus = Literal["pending", "enqueued", "delivered", "abandoned"]

# Above this exponent the doubling only overflows a float; every realistic cap is far below.
_MAX_EXPONENT = 62


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    """Delivery bookkeeping of one event. `pending`: committed, not yet handed to the queue."""

    event: SubmissionApproved
    quote_id: QuoteId
    status: OutboxStatus
    created_at: datetime
    # Attempt numbers already recorded, over every round; a number is recorded once.
    recorded_attempts: tuple[int, ...] = ()
    # Highest attempt number recorded when the current round was enqueued.
    attempt_base: int = 0
    # Delivery round: 0 after the approval, one more after each manual redelivery. A queue
    # that reserves the names of finished tasks needs a new task name for each round.
    round: int = 0
    enqueued_at: datetime | None = None
    last_attempt_at: datetime | None = None
    # Relay only: the calls it made in the current round and when the next one is due.
    dispatch_count: int = 0
    next_attempt_at: datetime | None = None

    @property
    def event_id(self) -> EventId:
        return self.event.event_id

    @property
    def terminal(self) -> bool:
        return self.status in ("delivered", "abandoned")

    def mark_enqueued(self, at: datetime) -> "OutboxRecord":
        """A `pending` record becomes `enqueued`; any other record is returned unchanged."""
        if self.status != "pending":
            return self
        return replace(self, status="enqueued", enqueued_at=at)

    def after_dispatch(self, next_attempt_at: datetime) -> "OutboxRecord":
        """The relay called the deliver endpoint and the delivery is still open."""
        return replace(
            self, dispatch_count=self.dispatch_count + 1, next_attempt_at=next_attempt_at
        )

    def due(self, now: datetime) -> bool:
        """An open delivery the relay should call now."""
        return not self.terminal and (self.next_attempt_at is None or self.next_attempt_at <= now)


def is_silent(record: OutboxRecord, now: datetime, retry_window_seconds: int) -> bool:
    """True for an enqueued delivery with no attempt or enqueue inside the retry window.

    The queue's own retries end with the window, so nothing more will arrive by itself.
    """
    if record.status != "enqueued" or record.enqueued_at is None:
        return False
    last_sign = record.enqueued_at
    if record.last_attempt_at is not None and record.last_attempt_at > last_sign:
        last_sign = record.last_attempt_at
    return last_sign < now - timedelta(seconds=retry_window_seconds)


def next_delay(
    retry_count: int, base: float, cap: float, random: Callable[[float, float], float]
) -> float:
    """Capped exponential backoff with full jitter: `random(0, min(cap, base * 2**retry_count))`."""
    ceiling = min(cap, base * 2 ** min(max(retry_count, 0), _MAX_EXPONENT))
    return random(0.0, ceiling)
