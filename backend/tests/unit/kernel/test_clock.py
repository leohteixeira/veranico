from datetime import UTC, datetime, timedelta, timezone

import pytest

from veranico.shared.kernel.clock import Clock, FixedClock, SystemClock


def test_fixed_clock_is_timezone_aware_utc() -> None:
    clock = FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))

    now = clock.now()

    assert now == datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    assert now.tzinfo is UTC
    assert clock.now() == now


def test_fixed_clock_converts_another_offset_to_utc() -> None:
    sao_paulo = timezone(timedelta(hours=-3))

    now = FixedClock(datetime(2026, 11, 10, 9, 0, tzinfo=sao_paulo)).now()

    assert now.tzinfo is UTC
    assert now == datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def test_fixed_clock_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 11, 10, 12, 0))  # noqa: DTZ001  # the naive value is the case under test


def test_fixed_clock_moves_only_when_advanced() -> None:
    clock = FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))

    clock.advance(timedelta(days=1, seconds=1))

    assert clock.now() == datetime(2026, 11, 11, 12, 0, 1, tzinfo=UTC)


def test_system_clock_is_timezone_aware_utc() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)

    assert now.tzinfo is UTC
    assert before <= now <= after


def test_both_clocks_satisfy_the_port() -> None:
    clocks: list[Clock] = [SystemClock(), FixedClock(datetime(2026, 1, 1, tzinfo=UTC))]

    assert all(clock.now().utcoffset() == timedelta(0) for clock in clocks)
