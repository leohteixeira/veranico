import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import builders
from veranico.modules.quoting.contracts import SubmissionApproved, SubmissionPayload
from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus, is_silent, next_delay
from veranico.shared.kernel.ids import EventId, SubmissionId

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
WINDOW = 3_600
EDGE = NOW - timedelta(seconds=WINDOW)
TICK = timedelta(microseconds=1)


def _record(status: OutboxStatus = "pending") -> OutboxRecord:
    view = builders.quote_view()
    event = SubmissionApproved(
        event_id=EventId("0190a8e0-0000-7000-8000-000000000001"),
        occurred_at=EDGE - timedelta(days=1),
        workspace_id=view.workspace_id,
        carrier_id="carrier-1",
        data=SubmissionPayload(
            quote_id=view.quote_id,
            submission_id=SubmissionId("S-000001"),
            location=view.location,
            cover=view.cover,
            premium=view.priced.premium.premium,
            rate_on_line=view.priced.premium.rate_on_line,
        ),
    )
    return OutboxRecord(
        event=event, quote_id=view.quote_id, status=status, created_at=event.occurred_at
    )


def test_marking_enqueued_moves_only_a_pending_record() -> None:
    pending = _record()

    enqueued = pending.mark_enqueued(NOW)

    assert (enqueued.status, enqueued.enqueued_at) == ("enqueued", NOW)
    assert enqueued.mark_enqueued(NOW + TICK) is enqueued
    for status in ("delivered", "abandoned"):
        terminal = _record(status)
        assert terminal.terminal
        assert terminal.mark_enqueued(NOW) is terminal
    assert not pending.terminal
    assert not enqueued.terminal


@pytest.mark.req("R-7-13")
def test_an_enqueued_record_is_silent_only_once_the_window_has_passed() -> None:
    just_inside = replace(_record("enqueued"), enqueued_at=EDGE)
    just_outside = replace(_record("enqueued"), enqueued_at=EDGE - TICK)

    assert not is_silent(just_inside, NOW, WINDOW)
    assert is_silent(just_outside, NOW, WINDOW)


@pytest.mark.req("R-7-13")
def test_a_recent_attempt_on_an_old_enqueue_is_not_silent() -> None:
    old_enqueue = EDGE - timedelta(hours=5)
    recent = replace(_record("enqueued"), enqueued_at=old_enqueue, last_attempt_at=EDGE)
    stale = replace(_record("enqueued"), enqueued_at=old_enqueue, last_attempt_at=EDGE - TICK)

    assert not is_silent(recent, NOW, WINDOW)
    assert is_silent(stale, NOW, WINDOW)


@pytest.mark.req("R-7-13")
def test_an_old_attempt_of_an_earlier_round_does_not_hide_a_recent_enqueue() -> None:
    redelivered = replace(
        _record("enqueued"), enqueued_at=EDGE, last_attempt_at=EDGE - timedelta(hours=5)
    )

    assert not is_silent(redelivered, NOW, WINDOW)


@pytest.mark.req("R-7-13")
@pytest.mark.parametrize("status", ["pending", "delivered", "abandoned"])
def test_only_an_enqueued_record_can_be_silent(status: OutboxStatus) -> None:
    ancient = EDGE - timedelta(days=30)
    record = replace(_record(status), enqueued_at=ancient, last_attempt_at=ancient)

    assert not is_silent(record, NOW, WINDOW)


@pytest.mark.req("R-7-11")
def test_the_relay_delay_stays_inside_the_capped_exponential_bound() -> None:
    generator = random.Random(20261111)
    base, cap = 1.0, 30.0

    for retry_count in range(11):
        bound = min(cap, base * 2**retry_count)
        delays = [next_delay(retry_count, base, cap, generator.uniform) for _ in range(200)]
        assert all(0.0 <= delay <= bound for delay in delays)
        # Full jitter spreads over the whole interval, it does not sit at the bound.
        assert min(delays) < bound / 2 < max(delays)


@pytest.mark.req("R-7-11")
def test_the_relay_delay_bound_doubles_until_the_cap() -> None:
    def upper(_low: float, high: float) -> float:
        return high

    assert [next_delay(count, 0.5, 30.0, upper) for count in range(8)] == [
        0.5,
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]
    assert next_delay(5_000, 0.5, 30.0, upper) == 30.0  # no float overflow on a long outage
