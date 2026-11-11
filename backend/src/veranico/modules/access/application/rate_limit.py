"""Rate limit of the public API: one token bucket per API key, in process memory.

`access` owns no collection for it, and a Firestore write per API request would cost more
than the abuse it prevents. With at most two instances a key can reach twice the
configured rate; that is accepted.
"""

from veranico.modules.access.domain.rate import Bucket, take
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import RateLimitedError
from veranico.shared.kernel.principal import Principal

MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    def __init__(
        self, clock: Clock, *, per_minute: int, max_tracked_keys: int = MAX_TRACKED_KEYS
    ) -> None:
        self._clock = clock
        self._per_minute = per_minute
        self._max_tracked_keys = max_tracked_keys
        # Ordered from the least to the most recently used key.
        self._buckets: dict[str, Bucket] = {}

    def check(self, principal: Principal) -> None:
        """Take one token from the key's bucket; raise `rate_limited` when it is empty.

        A principal that is not an API key is never limited.
        """
        if principal.kind != "api_key" or principal.key_id is None:
            return
        bucket, allowed = take(
            self._buckets.pop(principal.key_id, None), self._clock.now(), self._per_minute
        )
        self._buckets[principal.key_id] = bucket
        # The map cannot grow with every key ever seen: past the bound, the key idle the
        # longest is forgotten. Its bucket had the most time to refill, and a forgotten
        # key starts again with a full one.
        while len(self._buckets) > self._max_tracked_keys:
            del self._buckets[next(iter(self._buckets))]
        if not allowed:
            raise RateLimitedError

    @property
    def tracked_keys(self) -> int:
        return len(self._buckets)
