"""A token bucket as a pure function of (state, now). Integer arithmetic, so it is exact.

One token is `_UNITS_PER_TOKEN` units. A bucket of `per_minute` tokens refills
`per_minute` tokens per minute, which is `per_minute` units per microsecond.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

_UNITS_PER_TOKEN = 60_000_000  # microseconds in a minute


@dataclass(frozen=True, slots=True)
class Bucket:
    level: int  # in units, between 0 and the capacity
    updated_at: datetime


def take(bucket: Bucket | None, now: datetime, per_minute: int) -> tuple[Bucket, bool]:
    """Refill up to `now`, then take one token when there is one.

    `None` is a key never seen: its bucket starts full. Returns the new state and whether
    the call is allowed. The level never exceeds the capacity, however long the idleness.
    """
    capacity = per_minute * _UNITS_PER_TOKEN
    if bucket is None:
        level = capacity
    else:
        elapsed = max(now - bucket.updated_at, timedelta(0)) // timedelta(microseconds=1)
        level = min(capacity, bucket.level + elapsed * per_minute)
    if level < _UNITS_PER_TOKEN:
        return Bucket(level=level, updated_at=now), False
    return Bucket(level=level - _UNITS_PER_TOKEN, updated_at=now), True
