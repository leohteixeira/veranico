from datetime import UTC, datetime, timedelta

import pytest

from veranico.modules.access.domain.rate import Bucket, take

pytestmark = pytest.mark.req("R-10.2-3")

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def _drain(per_minute: int, now: datetime) -> Bucket:
    bucket: Bucket | None = None
    for _ in range(per_minute):
        bucket, allowed = take(bucket, now, per_minute)
        assert allowed
    assert bucket is not None
    return bucket


def test_a_new_bucket_allows_its_capacity_in_one_instant_and_no_more() -> None:
    bucket = _drain(7, NOW)

    bucket, allowed = take(bucket, NOW, 7)

    assert not allowed
    assert bucket.level == 0


def test_one_token_returns_after_the_refill_interval_exactly() -> None:
    per_minute = 7  # an interval that is not a whole number of microseconds: 60 s / 7
    bucket = _drain(per_minute, NOW)
    interval = timedelta(minutes=1) / per_minute

    _, too_early = take(bucket, NOW + interval - timedelta(microseconds=1), per_minute)
    after, allowed = take(bucket, NOW + interval + timedelta(microseconds=1), per_minute)
    _, second = take(after, NOW + interval + timedelta(microseconds=1), per_minute)

    assert not too_early
    assert allowed
    assert not second


def test_a_refused_call_does_not_push_the_refill_back() -> None:
    bucket = _drain(60, NOW)  # one token per second

    for millisecond in range(100, 1000, 100):
        bucket, allowed = take(bucket, NOW + timedelta(milliseconds=millisecond), 60)
        assert not allowed
    _, allowed = take(bucket, NOW + timedelta(seconds=1), 60)

    assert allowed


def test_long_idleness_fills_the_bucket_and_not_above_capacity() -> None:
    bucket = _drain(5, NOW)
    later = NOW + timedelta(days=30)

    allowed_calls = 0
    for _ in range(20):
        bucket, allowed = take(bucket, later, 5)
        allowed_calls += allowed

    assert allowed_calls == 5


def test_a_clock_that_goes_backwards_refills_nothing() -> None:
    bucket = _drain(5, NOW)

    _, allowed = take(bucket, NOW - timedelta(hours=1), 5)

    assert not allowed
