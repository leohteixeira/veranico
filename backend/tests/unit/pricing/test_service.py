"""The pricing use cases over `FakeClimateFacade`: contract models, rounding, codes, errors."""

import re
from typing import Any

import numpy as np
import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.modules.pricing.application.service import MAX_SIMULATION_N
from veranico.modules.pricing.contracts import (
    CoverDefinition,
    PricedCover,
    PricingFacade,
    SimulationOptions,
    Window,
)
from veranico.modules.pricing.module import PricingDeps, build
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    InsufficientHistoryError,
    InvalidArgumentsError,
    InvalidCoverError,
)
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money

RATE = re.compile(r"^-?\d+\.\d{6}$")
LIMIT_CENTS = 30_000_000
EIGHT_CODES = {
    "warning.trend_significant",
    "warning.seasons_excluded",
    "assumption.index_type",
    "assumption.window",
    "assumption.seasons_used",
    "assumption.simulation_method",
    "assumption.loads",
    "assumption.data_source",
}
RAINFALL = builders.cover(
    index_type="rainfall_below",
    start="10-01",
    end="03-31",
    trigger=600.0,
    exit=300.0,
    limit_cents=LIMIT_CENTS,
)
DRY_SPELL = builders.cover(
    index_type="dry_spell_above",
    start="10-01",
    end="03-31",
    trigger=9.0,
    exit=18.0,
    limit_cents=LIMIT_CENTS,
)
# Three hand-written seasons: totals 130, 70 and 40 mm over 01-11 to 01-20.
JANUARY = builders.cover(
    index_type="rainfall_below",
    start="01-11",
    end="01-20",
    trigger=100.0,
    exit=40.0,
    limit_cents=LIMIT_CENTS,
)


def facade_over(
    series: DailySeries, **pricing: Any
) -> tuple[PricingFacade, DatasetId, FakeClimateFacade]:
    climate = FakeClimateFacade()
    dataset = climate.add_series(series)
    settings = settings_for_tests(pricing=pricing) if pricing else settings_for_tests()
    module = build(PricingDeps(settings=settings, climate=climate))
    return module.facade, dataset.dataset_id, climate


def hand_series(
    daily_mm: dict[int, float], *, source: builders.Source = "synthetic"
) -> DailySeries:
    """Whole years of constant daily rain: `daily_mm[year]` millimetres every day of that year."""
    first, last = min(daily_mm), max(daily_mm)
    dates = np.arange(f"{first}-01-01", f"{last + 1}-01-01", dtype="datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    rain = np.array([daily_mm[int(year)] for year in years], dtype=np.float64)
    dataset = DatasetRef(
        dataset_id=builders.point_dataset_for(builders.LAT, builders.LON),
        kind="point",
        region_id=None,
        grid_point=GridPoint(lat=builders.LAT, lon=builders.LON),
        first_year=first,
        last_year=last,
        days=len(dates),
        missing_days=0,
        source=source,
    )
    return DailySeries(dataset=dataset, dates=dates, precipitation_mm=rain)


def money_fields(priced: PricedCover) -> list[Money]:
    backtest, simulation = priced.backtest, priced.simulation
    return [
        backtest.burn_cost,
        backtest.max_payout,
        simulation.expected_loss,
        simulation.std_dev,
        simulation.payout_1_in_10,
        simulation.payout_1_in_100,
        simulation.gap_to_burn_cost,
        priced.premium.premium,
        *[season.payout for season in backtest.seasons if season.payout is not None],
    ]


def codes(items: list[Coded]) -> list[str]:
    return [item.code for item in items]


def params_of(items: list[Coded], code: str) -> dict[str, str | int | float]:
    (item,) = [item for item in items if item.code == code]
    return item.params


@pytest.mark.req("R-5.4-1")
@pytest.mark.req("R-5.4-2")
@pytest.mark.req("R-5.7-1")
@pytest.mark.req("R-5.7-2")
@pytest.mark.req("R-5.7-3")
async def test_backtest_of_three_hand_written_seasons() -> None:
    # 13, 7 and 4 mm a day over a ten-day window: totals 130, 70 and 40 mm
    series = hand_series({2000: 13.0, 2001: 7.0, 2002: 4.0})
    pricing, dataset_id, _ = facade_over(series, min_seasons=3)

    result = await pricing.backtest(dataset_id, JANUARY)

    assert [(s.season, s.index_value, s.payout) for s in result.seasons] == [
        (2000, 130.0, Money(amount_cents=0)),
        (2001, 70.0, Money(amount_cents=15_000_000)),
        (2002, 40.0, Money(amount_cents=30_000_000)),
    ]
    assert result.dataset_id == dataset_id
    assert result.cover == JANUARY
    assert result.seasons_used == 3
    assert result.seasons_excluded == []
    assert result.trigger_frequency == "0.666667"
    assert result.burn_cost == Money(amount_cents=15_000_000)
    assert result.max_payout == Money(amount_cents=30_000_000)
    assert result.max_payout_season == 2002
    assert result.trend.slope_per_decade == -450.0
    assert RATE.fullmatch(result.trend.p_value)


@pytest.mark.req("R-5.7-1")
@pytest.mark.parametrize("cover", [RAINFALL, DRY_SPELL])
async def test_every_money_field_of_a_priced_cover_is_integer_centavos(
    cover: CoverDefinition,
) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    priced = await pricing.price(dataset_id, cover, SimulationOptions())

    fields = money_fields(priced)
    assert len(fields) > 8
    for field in fields:
        assert isinstance(field, Money)
        assert type(field.amount_cents) is int
        assert field.currency == "BRL"


@pytest.mark.req("R-5.7-2")
@pytest.mark.parametrize("cover", [RAINFALL, DRY_SPELL])
async def test_every_rate_of_a_priced_cover_has_six_decimal_places(cover: CoverDefinition) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    priced = await pricing.price(dataset_id, cover, SimulationOptions())

    for rate in (
        priced.backtest.trigger_frequency,
        priced.backtest.trend.p_value,
        priced.simulation.probability_of_payout,
        priced.premium.rate_on_line,
        priced.premium.risk_load,
        priced.premium.expense_load,
    ):
        assert RATE.fullmatch(rate)


@pytest.mark.req("R-5.7-3")
async def test_index_values_and_the_slope_have_one_decimal_place() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    result = await pricing.backtest(dataset_id, RAINFALL)

    values = [season.index_value for season in result.seasons]
    assert len({value for value in values if value != int(value)}) > 10  # real, uneven totals
    for value in [*values, result.trend.slope_per_decade]:
        assert value == round(value, 1)


@pytest.mark.req("R-5.7-1")
@pytest.mark.req("R-5.5-4")
async def test_gap_to_burn_cost_is_the_difference_of_the_two_rounded_figures() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    priced = await pricing.price(dataset_id, RAINFALL, SimulationOptions())

    assert priced.simulation.gap_to_burn_cost.amount_cents == (
        priced.simulation.expected_loss.amount_cents - priced.backtest.burn_cost.amount_cents
    )
    assert priced.simulation.expected_loss.amount_cents > 0


@pytest.mark.req("R-5.6-1")
@pytest.mark.req("R-5.6-2")
@pytest.mark.req("R-5.6-3")
async def test_loads_default_to_the_settings_values_and_shape_the_premium() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    priced = await pricing.price(dataset_id, RAINFALL, SimulationOptions())

    assert priced.premium.risk_load == "0.300000"
    assert priced.premium.expense_load == "0.150000"
    expected_loss = priced.simulation.expected_loss.amount_cents
    std_dev = priced.simulation.std_dev.amount_cents
    by_hand = expected_loss + 0.3 * std_dev + 0.15 * expected_loss
    # the premium is rounded from unrounded inputs: at most a centavo from the hand figure
    assert priced.premium.premium.amount_cents == pytest.approx(by_hand, abs=1.0)
    assert float(priced.premium.rate_on_line) == pytest.approx(by_hand / LIMIT_CENTS, abs=1e-6)


@pytest.mark.req("R-5.6-3")
async def test_loads_overridden_in_settings_change_the_premium() -> None:
    series = builders.daily_series(seed=0)
    default, dataset_id, _ = facade_over(series)
    loaded, _, _ = facade_over(series, risk_load=0.5, expense_load=0.25)

    base = await default.price(dataset_id, RAINFALL, SimulationOptions())
    priced = await loaded.price(dataset_id, RAINFALL, SimulationOptions())

    assert priced.premium.risk_load == "0.500000"
    assert priced.premium.expense_load == "0.250000"
    assert priced.simulation == base.simulation
    assert priced.premium.premium.amount_cents > base.premium.premium.amount_cents
    expected_loss = priced.simulation.expected_loss.amount_cents
    by_hand = expected_loss + 0.5 * priced.simulation.std_dev.amount_cents + 0.25 * expected_loss
    assert priced.premium.premium.amount_cents == pytest.approx(by_hand, abs=1.0)


@pytest.mark.req("R-5.5-3")
async def test_simulation_defaults_come_from_settings_when_the_caller_sets_none() -> None:
    series = builders.daily_series(seed=0)
    default, dataset_id, _ = facade_over(series)
    configured, _, _ = facade_over(series, simulation_n=5_000, simulation_seed=7)

    base = await default.price(dataset_id, DRY_SPELL, SimulationOptions())
    priced = await configured.price(dataset_id, DRY_SPELL, SimulationOptions())

    assert (base.simulation.n, base.simulation.seed) == (100_000, 42)
    assert (priced.simulation.n, priced.simulation.seed) == (5_000, 7)
    assert priced.simulation.expected_loss != base.simulation.expected_loss
    assert params_of(priced.assumptions, "assumption.simulation_method") == {
        "method": "bootstrap",
        "n": 5_000,
        "seed": 7,
    }


@pytest.mark.req("R-5.5-3")
async def test_options_set_by_the_caller_win_over_the_settings() -> None:
    pricing, dataset_id, _ = facade_over(
        builders.daily_series(seed=0), simulation_n=5_000, simulation_seed=7
    )

    priced = await pricing.price(dataset_id, DRY_SPELL, SimulationOptions(n=2_000, seed=99))
    only_n = await pricing.price(dataset_id, DRY_SPELL, SimulationOptions(n=2_000))

    assert (priced.simulation.n, priced.simulation.seed) == (2_000, 99)
    assert (only_n.simulation.n, only_n.simulation.seed) == (2_000, 7)


@pytest.mark.req("R-5-1")
@pytest.mark.parametrize("cover", [RAINFALL, DRY_SPELL])
async def test_pricing_twice_with_the_same_options_returns_equal_objects(
    cover: CoverDefinition,
) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    first = await pricing.price(dataset_id, cover, SimulationOptions(n=20_000, seed=5))
    second = await pricing.price(dataset_id, cover, SimulationOptions(n=20_000, seed=5))

    assert first == second
    assert first.backtest == await pricing.backtest(dataset_id, cover)


@pytest.mark.req("R-5.5-1")
@pytest.mark.req("R-5.5-2")
async def test_simulation_method_follows_the_index_type() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    rainfall = await pricing.price(dataset_id, RAINFALL, SimulationOptions())
    dry_spell = await pricing.price(dataset_id, DRY_SPELL, SimulationOptions())

    assert rainfall.simulation.method == "gamma_mle"
    assert dry_spell.simulation.method == "bootstrap"
    assert params_of(rainfall.assumptions, "assumption.simulation_method")["method"] == "gamma_mle"


@pytest.mark.req("R-5.5-1")
async def test_zero_seasonal_total_reports_the_bootstrap_through_the_assumption() -> None:
    daily_mm = {year: 5.0 + year % 7 for year in range(2000, 2025)}
    daily_mm[2010] = 0.0  # a season with no rain at all: maximum likelihood is undefined
    pricing, dataset_id, _ = facade_over(hand_series(daily_mm))

    priced = await pricing.price(dataset_id, JANUARY, SimulationOptions())

    assert priced.simulation.method == "bootstrap"
    assert params_of(priced.assumptions, "assumption.simulation_method") == {
        "method": "bootstrap",
        "n": 100_000,
        "seed": 42,
    }


async def test_codes_are_the_six_assumptions_in_order_when_nothing_is_wrong() -> None:
    # same-year window on whole years, constant totals: no excluded season, no trend
    pricing, dataset_id, _ = facade_over(hand_series(dict.fromkeys(range(2000, 2025), 6.0)))

    priced = await pricing.price(dataset_id, JANUARY, SimulationOptions())

    assert priced.backtest.warnings == []
    assert codes(priced.assumptions) == [
        "assumption.index_type",
        "assumption.window",
        "assumption.seasons_used",
        "assumption.simulation_method",
        "assumption.loads",
        "assumption.data_source",
    ]
    assert params_of(priced.assumptions, "assumption.index_type") == {
        "index_type": "rainfall_below"
    }
    assert params_of(priced.assumptions, "assumption.window") == {"start": "01-11", "end": "01-20"}
    assert params_of(priced.assumptions, "assumption.seasons_used") == {
        "seasons_used": 25,
        "first_season": 2000,
        "last_season": 2024,
    }
    assert params_of(priced.assumptions, "assumption.loads") == {
        "risk_load_rate": "0.300000",
        "expense_load_rate": "0.150000",
    }


@pytest.mark.req("R-5.4-4")
@pytest.mark.req("R-5.1-3")
async def test_the_codes_emitted_are_the_eight_of_the_contracts_and_no_other() -> None:
    # rain falling steadily year after year (a significant trend) and a crossing window
    # (seasons cut by both ends of the series are excluded)
    series = hand_series({year: 10.0 - 0.2 * (year - 2000) for year in range(2000, 2025)})
    pricing, dataset_id, _ = facade_over(series)
    cover = builders.cover(
        index_type="rainfall_below", start="12-22", end="01-10", trigger=150.0, exit=80.0
    )

    priced = await pricing.price(dataset_id, cover, SimulationOptions())

    emitted = [*priced.backtest.warnings, *priced.assumptions]
    assert set(codes(emitted)) == EIGHT_CODES
    assert len(emitted) == 8
    assert codes(priced.backtest.warnings) == [
        "warning.trend_significant",
        "warning.seasons_excluded",
    ]
    assert priced.backtest.trend.significant
    assert params_of(emitted, "warning.trend_significant") == {
        "slope_per_decade": priced.backtest.trend.slope_per_decade,
        "direction": "decreasing",
    }
    assert priced.backtest.trend.slope_per_decade < 0
    assert priced.backtest.seasons_excluded == [1999, 2024]
    assert params_of(emitted, "warning.seasons_excluded") == {"count": 2, "seasons": "1999, 2024"}
    for item in emitted:
        for name, value in item.params.items():
            if name.endswith("_rate"):
                assert isinstance(value, str)
                assert RATE.fullmatch(value)
            if name.endswith("_cents"):
                assert type(value) is int
            if isinstance(value, str) and RATE.fullmatch(value):
                assert name.endswith("_rate")


@pytest.mark.req("R-5.4-4")
async def test_rising_trend_reports_the_increasing_direction() -> None:
    series = hand_series({year: 5.0 + 0.2 * (year - 2000) for year in range(2000, 2025)})
    pricing, dataset_id, _ = facade_over(series)

    result = await pricing.backtest(dataset_id, JANUARY)

    assert params_of(result.warnings, "warning.trend_significant") == {
        "slope_per_decade": 20.0,  # 0.2 mm a day more each year over ten days, per decade
        "direction": "increasing",
    }


@pytest.mark.parametrize("source", ["synthetic", "era5-land/cds", "era5/open-meteo"])
async def test_data_source_assumption_reports_the_source_of_the_series(
    source: builders.Source,
) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0, source=source))

    priced = await pricing.price(dataset_id, RAINFALL, SimulationOptions(n=1_000))

    assert params_of(priced.assumptions, "assumption.data_source") == {"source": source}


async def test_backtest_seasons_are_the_usable_seasons_in_ascending_order() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    result = await pricing.backtest(dataset_id, RAINFALL)  # 10-01 to 03-31 crosses the year

    seasons = [season.season for season in result.seasons]
    assert seasons == list(range(1950, 2024))
    assert result.seasons_used == 74
    assert result.seasons_excluded == [1949, 2024]


async def test_season_series_has_no_payout_without_a_limit_and_money_with_one() -> None:
    series = hand_series({2000: 13.0, 2001: 7.0, 2002: 4.0})
    pricing, dataset_id, _ = facade_over(series, min_seasons=3)

    bare = await pricing.season_series(dataset_id, JANUARY.index, None)
    paid = await pricing.season_series(dataset_id, JANUARY.index, JANUARY.limit)

    assert bare.dataset_id == dataset_id
    assert bare.index == JANUARY.index
    assert [(s.season, s.index_value, s.payout) for s in bare.seasons] == [
        (2000, 130.0, None),
        (2001, 70.0, None),
        (2002, 40.0, None),
    ]
    assert [s.payout for s in paid.seasons] == [
        Money(amount_cents=0),
        Money(amount_cents=15_000_000),
        Money(amount_cents=30_000_000),
    ]
    assert paid.seasons_excluded == []


@pytest.mark.req("R-9.4-5")
async def test_extreme_seasons_are_ranked_worst_first_with_rounded_figures() -> None:
    daily_mm = {year: 5.0 + (year * 7) % 20 for year in range(2000, 2020)}
    daily_mm[2007] = 0.5  # the driest: 5 mm over the window
    daily_mm[2013] = 1.25  # then 12.5 mm
    pricing, dataset_id, _ = facade_over(hand_series(daily_mm))

    worst = await pricing.extreme_seasons(
        dataset_id, "rainfall_below", Window(start="01-11", end="01-20"), 3
    )

    assert [(item.rank, item.season, item.index_value) for item in worst[:2]] == [
        (1, 2007, 5.0),
        (2, 2013, 12.5),
    ]
    # 20 seasons: 21 / 1, 21 / 2 and 21 / 3 years, with one decimal place
    assert [item.return_period_years for item in worst] == [21.0, 10.5, 7.0]


async def test_unknown_dataset_raises_dataset_not_found() -> None:
    pricing, _, _ = facade_over(builders.daily_series(seed=0))
    unknown = builders.point_dataset_for(-20.0, -45.0)
    window = Window(start="01-11", end="01-20")

    with pytest.raises(DatasetNotFoundError):
        await pricing.backtest(unknown, RAINFALL)
    with pytest.raises(DatasetNotFoundError):
        await pricing.price(unknown, RAINFALL, SimulationOptions())
    with pytest.raises(DatasetNotFoundError):
        await pricing.season_series(unknown, RAINFALL.index, None)
    with pytest.raises(DatasetNotFoundError):
        await pricing.extreme_seasons(unknown, "rainfall_below", window, 3)


async def test_nineteen_usable_seasons_raise_insufficient_history() -> None:
    nineteen = hand_series(dict.fromkeys(range(2000, 2019), 6.0))
    pricing, dataset_id, _ = facade_over(nineteen)
    window = Window(start="01-11", end="01-20")

    with pytest.raises(InsufficientHistoryError):
        await pricing.backtest(dataset_id, JANUARY)
    with pytest.raises(InsufficientHistoryError):
        await pricing.price(dataset_id, JANUARY, SimulationOptions())
    with pytest.raises(InsufficientHistoryError):
        await pricing.season_series(dataset_id, JANUARY.index, None)
    with pytest.raises(InsufficientHistoryError):
        await pricing.extreme_seasons(dataset_id, "rainfall_below", window, 3)


async def test_twenty_usable_seasons_are_enough() -> None:
    pricing, dataset_id, _ = facade_over(hand_series(dict.fromkeys(range(2000, 2020), 6.0)))

    assert (await pricing.backtest(dataset_id, JANUARY)).seasons_used == 20


@pytest.mark.req("R-5.3-3")
@pytest.mark.parametrize(
    "cover",
    [
        builders.cover(index_type="rainfall_below", trigger=100.0, exit=120.0),
        builders.cover(index_type="dry_spell_above", trigger=10.0, exit=5.0),
        builders.cover(start="02-29", end="03-31"),
        builders.cover(limit_cents=0),
    ],
)
async def test_invalid_cover_is_rejected_before_the_series_is_read(cover: CoverDefinition) -> None:
    pricing, dataset_id, climate = facade_over(builders.daily_series(seed=0))

    with pytest.raises(InvalidCoverError):
        await pricing.backtest(dataset_id, cover)
    with pytest.raises(InvalidCoverError):
        await pricing.price(dataset_id, cover, SimulationOptions())
    with pytest.raises(InvalidCoverError):
        await pricing.season_series(dataset_id, cover.index, cover.limit)
    assert climate.calls == []


async def test_window_that_is_not_real_is_invalid_for_extreme_seasons() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    with pytest.raises(InvalidCoverError):
        await pricing.extreme_seasons(
            dataset_id, "rainfall_below", Window(start="13-01", end="01-20"), 3
        )


@pytest.mark.parametrize("n", [0, -5, MAX_SIMULATION_N + 1])
async def test_simulation_size_out_of_bounds_is_invalid_arguments(n: int) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    with pytest.raises(InvalidArgumentsError):
        await pricing.price(dataset_id, RAINFALL, SimulationOptions(n=n))


@pytest.mark.req("R-9.4-5")
@pytest.mark.parametrize("top_n", [0, -1, 11])
async def test_top_n_outside_one_to_ten_is_invalid_arguments(top_n: int) -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))

    with pytest.raises(InvalidArgumentsError):
        await pricing.extreme_seasons(
            dataset_id, "rainfall_below", Window(start="01-11", end="01-20"), top_n
        )


@pytest.mark.req("R-9.4-5")
async def test_top_n_of_one_and_of_ten_are_accepted() -> None:
    pricing, dataset_id, _ = facade_over(builders.daily_series(seed=0))
    window = Window(start="01-11", end="01-20")

    assert len(await pricing.extreme_seasons(dataset_id, "rainfall_below", window, 1)) == 1
    assert len(await pricing.extreme_seasons(dataset_id, "rainfall_below", window, 10)) == 10
