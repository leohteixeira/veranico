from datetime import UTC, datetime, timedelta

import pytest

from veranico.modules.access.application.rate_limit import RateLimiter
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import RateLimitedError
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

pytestmark = pytest.mark.req("R-10.2-3")

PER_MINUTE = 6  # one token every ten seconds
WORKSPACE = WorkspaceId("a" * 32)


def _key(key_id: str) -> Principal:
    return Principal(workspace_id=WORKSPACE, kind="api_key", key_id=key_id)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 11, 12, 0, tzinfo=UTC))


@pytest.fixture
def limiter(clock: FixedClock) -> RateLimiter:
    return RateLimiter(clock, per_minute=PER_MINUTE)


def test_a_key_may_use_its_capacity_in_one_instant_and_the_next_call_is_limited(
    limiter: RateLimiter,
) -> None:
    for _ in range(PER_MINUTE):
        limiter.check(_key("k1"))

    with pytest.raises(RateLimitedError) as raised:
        limiter.check(_key("k1"))

    assert raised.value.code == "rate_limited"


def test_one_more_call_passes_after_the_refill_interval(
    limiter: RateLimiter, clock: FixedClock
) -> None:
    for _ in range(PER_MINUTE):
        limiter.check(_key("k1"))

    clock.advance(timedelta(seconds=9))
    with pytest.raises(RateLimitedError):
        limiter.check(_key("k1"))
    clock.advance(timedelta(seconds=1))
    limiter.check(_key("k1"))
    with pytest.raises(RateLimitedError):
        limiter.check(_key("k1"))


def test_a_second_key_is_unaffected_by_the_first(limiter: RateLimiter) -> None:
    for _ in range(PER_MINUTE):
        limiter.check(_key("k1"))
    with pytest.raises(RateLimitedError):
        limiter.check(_key("k1"))

    for _ in range(PER_MINUTE):
        limiter.check(_key("k2"))  # the same workspace, its own bucket


def test_a_browser_principal_is_never_limited(limiter: RateLimiter) -> None:
    browser = Principal(workspace_id=WORKSPACE, kind="browser")

    for _ in range(PER_MINUTE * 10):
        limiter.check(browser)

    assert limiter.tracked_keys == 0


def test_after_long_idleness_the_bucket_is_full_and_not_above_capacity(
    limiter: RateLimiter, clock: FixedClock
) -> None:
    for _ in range(PER_MINUTE):
        limiter.check(_key("k1"))

    clock.advance(timedelta(days=3))
    for _ in range(PER_MINUTE):
        limiter.check(_key("k1"))
    with pytest.raises(RateLimitedError):
        limiter.check(_key("k1"))


def test_the_map_does_not_exceed_its_bound_when_many_keys_are_seen_once(
    clock: FixedClock,
) -> None:
    limiter = RateLimiter(clock, per_minute=PER_MINUTE, max_tracked_keys=50)

    for number in range(1_000):
        limiter.check(_key(f"key-{number}"))
        assert limiter.tracked_keys <= 50

    assert limiter.tracked_keys == 50


def test_a_key_in_use_survives_the_pruning_with_its_bucket(clock: FixedClock) -> None:
    limiter = RateLimiter(clock, per_minute=PER_MINUTE, max_tracked_keys=5)
    for _ in range(PER_MINUTE):
        limiter.check(_key("busy"))

    for number in range(4):  # the map is full, and "busy" is the oldest entry
        limiter.check(_key(f"other-{number}"))
    with pytest.raises(RateLimitedError):
        limiter.check(_key("busy"))  # used again: now the most recent entry
    for number in range(4, 8):
        limiter.check(_key(f"other-{number}"))

    with pytest.raises(RateLimitedError):
        limiter.check(_key("busy"))
