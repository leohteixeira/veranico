from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.access.memory import MemorySpendStore
from veranico.modules.access.application.spend import Spend
from veranico.modules.access.contracts import Admission, ModelUsage
from veranico.modules.access.domain.cost import TokenPrices, UnknownModelPriceError
from veranico.shared.infrastructure.settings import AccessSettings
from veranico.shared.kernel.clock import FixedClock

NOW = datetime(2026, 11, 11, 21, 30, tzinfo=UTC)
MODEL = "invented-model"
# Invented prices: one token of input costs exactly one micro-dollar, output two.
PRICES = {MODEL: TokenPrices(input=1_000_000, output=2_000_000, cache_read=0, cache_write=0)}
DAY_CEILING = 1_000
MONTH_CEILING = 2_500


def _usage(cost: int) -> ModelUsage:
    return ModelUsage(model=MODEL, input_tokens=cost, output_tokens=0)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def store() -> MemorySpendStore:
    return MemorySpendStore()


@pytest.fixture
def spend(store: MemorySpendStore, clock: FixedClock) -> Spend:
    return Spend(
        store,
        clock,
        prices=PRICES,
        day_ceiling_usd_micros=DAY_CEILING,
        month_ceiling_usd_micros=MONTH_CEILING,
    )


@pytest.mark.req("R-10.3-3", "R-10.3-4")
async def test_with_nothing_spent_a_call_is_allowed(spend: Spend) -> None:
    assert await spend.may_spend() == Admission(allowed=True, reason="ok", allowance=None)


@pytest.mark.req("R-10.3-4")
async def test_may_spend_writes_nothing(spend: Spend, store: MemorySpendStore) -> None:
    for _ in range(5):
        await spend.may_spend()

    assert store.writes == 0
    assert store.days == {}
    assert store.months == {}


@pytest.mark.req("R-10.3-3", "R-10.3-4")
async def test_record_returns_the_cost_and_adds_it_to_the_day_and_the_month(
    spend: Spend, store: MemorySpendStore
) -> None:
    usage = ModelUsage(model=MODEL, input_tokens=120, output_tokens=40)

    first = await spend.record(usage)
    second = await spend.record(usage)

    assert spend.cost_of(usage) == 120 + 2 * 40
    assert first.cost_usd_micros == second.cost_usd_micros == 200
    assert store.days == {"2026-11-11": 400}
    assert store.months == {"2026-11": 400}
    assert store.calls == {"2026-11-11": 2, "2026-11": 2}


@pytest.mark.req("R-10.3-3")
async def test_the_day_ceiling_refuses_once_the_day_total_reaches_it(spend: Spend) -> None:
    await spend.record(_usage(DAY_CEILING - 1))
    below = await spend.may_spend()
    await spend.record(_usage(1))
    at = await spend.may_spend()

    assert below.allowed
    assert at == Admission(allowed=False, reason="day_ceiling", allowance=None)
    assert await spend.reached() == "day_ceiling"


@pytest.mark.req("R-10.3-3")
async def test_the_next_utc_day_allows_again_and_the_month_keeps_the_spend(
    spend: Spend, store: MemorySpendStore, clock: FixedClock
) -> None:
    await spend.record(_usage(DAY_CEILING))
    assert not (await spend.may_spend()).allowed

    clock.advance(timedelta(hours=2, minutes=29, seconds=59))  # 23:59:59 UTC
    still = await spend.may_spend()
    clock.advance(timedelta(seconds=1))  # 00:00:00 UTC on the 12th
    next_day = await spend.may_spend()
    await spend.record(_usage(10))

    assert not still.allowed
    assert next_day.allowed
    assert store.days == {"2026-11-11": DAY_CEILING, "2026-11-12": 10}
    assert store.months == {"2026-11": DAY_CEILING + 10}


@pytest.mark.req("R-10.3-3")
async def test_the_month_ceiling_refuses_also_on_a_new_day(spend: Spend, clock: FixedClock) -> None:
    for _ in range(3):  # 900 a day stays under the day ceiling; 2,700 passes the month's
        await spend.record(_usage(900))
        clock.advance(timedelta(days=1))

    admission = await spend.may_spend()

    assert admission == Admission(allowed=False, reason="month_ceiling", allowance=None)


@pytest.mark.req("R-10.3-3")
async def test_a_new_month_starts_from_zero(
    spend: Spend, store: MemorySpendStore, clock: FixedClock
) -> None:
    for _ in range(3):
        await spend.record(_usage(900))
        clock.advance(timedelta(days=1))
    assert (await spend.may_spend()).reason == "month_ceiling"

    clock.advance(datetime(2026, 12, 1, tzinfo=UTC) - clock.now())
    admission = await spend.may_spend()
    await spend.record(_usage(5))

    assert admission.allowed
    assert store.months == {"2026-11": 2_700, "2026-12": 5}


@pytest.mark.req("R-10.3-3")
async def test_when_both_ceilings_are_reached_the_reason_is_the_day_ceiling(spend: Spend) -> None:
    await spend.record(_usage(MONTH_CEILING))

    assert (await spend.may_spend()).reason == "day_ceiling"


@pytest.mark.req("R-10.3-4")
async def test_recording_is_never_refused_by_a_ceiling(
    spend: Spend, store: MemorySpendStore
) -> None:
    await spend.record(_usage(MONTH_CEILING))

    recorded = await spend.record(_usage(7))  # a call that was in flight

    assert recorded.cost_usd_micros == 7
    assert store.days == {"2026-11-11": MONTH_CEILING + 7}


@pytest.mark.req("R-10.3-3")
async def test_a_model_without_prices_raises_and_records_nothing(
    spend: Spend, store: MemorySpendStore
) -> None:
    usage = ModelUsage(model="unpriced-model", input_tokens=1, output_tokens=1)

    with pytest.raises(UnknownModelPriceError):
        spend.cost_of(usage)
    with pytest.raises(UnknownModelPriceError):
        await spend.record(usage)

    assert store.writes == 0


@pytest.mark.req("R-10.3-3")
def test_the_default_ceilings_are_fifty_cents_a_day_and_ten_dollars_a_month() -> None:
    settings = AccessSettings()

    assert settings.day_ceiling_usd_micros == 500_000
    assert settings.month_ceiling_usd_micros == 10_000_000
