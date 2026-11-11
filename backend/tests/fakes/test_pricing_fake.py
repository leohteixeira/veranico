import re

import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from veranico.modules.pricing.contracts import (
    CellMetricRequest,
    CoverDefinition,
    IndexDefinition,
    SimulationOptions,
    Window,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    InsufficientHistoryError,
    InvalidArgumentsError,
    InvalidCoverError,
)
from veranico.shared.kernel.money import Money

DATASET = builders.point_dataset_for(builders.LAT, builders.LON)
OPTIONS = SimulationOptions()
RATE = re.compile(r"^-?\d+\.\d{6}$")
PRICING_CODES = {
    "warning.trend_significant": {"slope_per_decade", "direction"},
    "warning.seasons_excluded": {"count", "seasons"},
    "assumption.index_type": {"index_type"},
    "assumption.window": {"start", "end"},
    "assumption.seasons_used": {"seasons_used", "first_season", "last_season"},
    "assumption.simulation_method": {"method", "n", "seed"},
    "assumption.loads": {"risk_load_rate", "expense_load_rate"},
    "assumption.data_source": {"source"},
}


def pricing(**dataset: object) -> FakePricingFacade:
    fake = FakePricingFacade()
    fake.add_dataset(DATASET, **dataset)  # type: ignore[arg-type]  # keyword passthrough
    return fake


def with_index(**changes: object) -> CoverDefinition:
    base = builders.cover()
    return CoverDefinition(index=base.index.model_copy(update=changes), limit=base.limit)


@pytest.mark.parametrize(
    "cover",
    [
        builders.cover(index_type="rainfall_below", trigger=300.0, exit=600.0),
        builders.cover(index_type="rainfall_below", trigger=300.0, exit=300.0),
        builders.cover(index_type="dry_spell_above", trigger=40.0, exit=20.0),
        builders.cover(index_type="dry_spell_above", trigger=20.0, exit=20.0),
    ],
    ids=["below-exit-above", "below-exit-equal", "spell-exit-below", "spell-exit-equal"],
)
async def test_an_exit_on_the_wrong_side_is_invalid_cover(cover: CoverDefinition) -> None:
    fake = pricing()

    with pytest.raises(InvalidCoverError):
        await fake.backtest(DATASET, cover)
    with pytest.raises(InvalidCoverError):
        await fake.price(DATASET, cover, OPTIONS)
    with pytest.raises(InvalidCoverError):
        await fake.season_series(DATASET, cover.index, None)


@pytest.mark.parametrize("bound", ["02-29", "02-30", "13-01", "00-10", "1-1", "march", ""])
async def test_an_empty_window_is_invalid_cover(bound: str) -> None:
    fake = pricing()

    with pytest.raises(InvalidCoverError):
        await fake.price(DATASET, with_index(window=Window(start=bound, end="03-31")), OPTIONS)
    with pytest.raises(InvalidCoverError):
        await fake.backtest(DATASET, with_index(window=Window(start="10-01", end=bound)))
    with pytest.raises(InvalidCoverError):
        await fake.extreme_seasons(DATASET, "rainfall_below", Window(start=bound, end="03-31"), 3)


async def test_a_one_day_window_and_a_window_crossing_the_year_are_valid() -> None:
    fake = pricing()

    await fake.backtest(DATASET, with_index(window=Window(start="01-15", end="01-15")))
    await fake.backtest(DATASET, with_index(window=Window(start="11-15", end="02-15")))


@pytest.mark.parametrize("limit_cents", [0, -1])
async def test_a_non_positive_limit_is_invalid_cover(limit_cents: int) -> None:
    fake = pricing()
    cover = CoverDefinition(index=builders.cover().index, limit=Money(amount_cents=limit_cents))

    with pytest.raises(InvalidCoverError):
        await fake.backtest(DATASET, cover)
    with pytest.raises(InvalidCoverError):
        await fake.price(DATASET, cover, OPTIONS)
    with pytest.raises(InvalidCoverError):
        await fake.season_series(DATASET, cover.index, cover.limit)


async def test_fewer_than_twenty_usable_seasons_is_insufficient_history() -> None:
    nineteen = pricing(seasons=19)
    twenty = pricing(seasons=20)
    excluded = pricing(seasons=21, seasons_excluded=(1950, 1951))

    with pytest.raises(InsufficientHistoryError):
        await nineteen.price(DATASET, builders.cover(), OPTIONS)
    with pytest.raises(InsufficientHistoryError):
        await excluded.backtest(DATASET, builders.cover())
    assert (await twenty.backtest(DATASET, builders.cover())).seasons_used == 20


async def test_an_unknown_dataset_is_dataset_not_found() -> None:
    fake = FakePricingFacade()
    cover = builders.cover()

    with pytest.raises(DatasetNotFoundError):
        await fake.backtest(DATASET, cover)
    with pytest.raises(DatasetNotFoundError):
        await fake.price(DATASET, cover, OPTIONS)
    with pytest.raises(DatasetNotFoundError):
        await fake.season_series(DATASET, cover.index, None)
    with pytest.raises(DatasetNotFoundError):
        await fake.extreme_seasons(DATASET, "rainfall_below", cover.index.window, 3)


async def test_a_dataset_of_the_given_climate_facade_is_known() -> None:
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series(first_year=1990, last_year=2019))
    fake = FakePricingFacade(climate)

    priced = await fake.price(dataset.dataset_id, builders.cover(), OPTIONS)

    assert priced.backtest.seasons_used == 30
    assert priced.backtest.seasons[0].season == 1990
    assert priced.assumptions[-1] == Coded(
        code="assumption.data_source", params={"source": "synthetic"}
    )
    with pytest.raises(DatasetNotFoundError):
        await fake.price(builders.point_dataset_for(-21.2, -47.8), builders.cover(), OPTIONS)


async def test_identical_input_gives_identical_figures_and_other_input_differs() -> None:
    fake = pricing()
    cover = builders.cover(limit_cents=10_000_000)

    first = await fake.price(DATASET, cover, OPTIONS)
    second = await fake.price(DATASET, cover, OPTIONS)
    larger = await fake.price(DATASET, builders.cover(limit_cents=20_000_000), OPTIONS)

    assert first == second
    assert first == builders.priced_cover(cover, dataset_id=DATASET)
    assert larger.premium.premium.amount_cents == 2 * first.premium.premium.amount_cents
    assert (await fake.backtest(DATASET, cover)) == first.backtest


async def test_figures_are_integer_centavos_derived_from_the_limit() -> None:
    priced = await pricing().price(DATASET, builders.cover(limit_cents=10_000_000), OPTIONS)
    backtest, simulation, premium = priced.backtest, priced.simulation, priced.premium

    assert backtest.seasons_used == 30
    assert backtest.max_payout == Money(amount_cents=2_500_000)
    assert backtest.max_payout_season == 1950
    assert backtest.trigger_frequency == "0.200000"  # 6 of 30 seasons
    assert backtest.burn_cost == Money(amount_cents=500_000)  # 6 * 2,500,000 / 30
    assert simulation.gap_to_burn_cost.amount_cents == (
        simulation.expected_loss.amount_cents - backtest.burn_cost.amount_cents
    )
    assert premium.premium.amount_cents >= simulation.expected_loss.amount_cents
    assert premium.rate_on_line == builders.rate(premium.premium.amount_cents, 10_000_000)
    money = [
        backtest.burn_cost,
        backtest.max_payout,
        simulation.expected_loss,
        simulation.std_dev,
        simulation.payout_1_in_10,
        simulation.payout_1_in_100,
        simulation.gap_to_burn_cost,
        premium.premium,
        *(season.payout for season in backtest.seasons),
    ]
    assert all(isinstance(value, Money) and type(value.amount_cents) is int for value in money)
    rates = [
        backtest.trigger_frequency,
        backtest.trend.p_value,
        simulation.probability_of_payout,
        premium.rate_on_line,
        premium.risk_load,
        premium.expense_load,
    ]
    assert all(RATE.match(value) for value in rates)
    assert all(
        season.index_value == float(f"{season.index_value:.1f}") for season in backtest.seasons
    )


async def test_a_paying_season_is_strictly_beyond_the_trigger() -> None:
    for index_type in ("rainfall_below", "dry_spell_above"):
        cover = builders.cover(index_type=index_type)
        backtest = await pricing().backtest(DATASET, cover)
        trigger = cover.index.trigger
        for season in backtest.seasons:
            assert season.payout is not None
            beyond = season.index_value < trigger
            if index_type == "dry_spell_above":
                beyond = season.index_value > trigger
            assert (season.payout.amount_cents > 0) == beyond


async def test_only_the_eight_pricing_codes_are_emitted_with_their_parameters() -> None:
    fake = pricing(seasons=40, seasons_excluded=(1951, 1960), trend_significant=True)
    emitted: list[Coded] = []
    for index_type in ("rainfall_below", "dry_spell_above"):
        cover = builders.cover(index_type=index_type)
        priced = await fake.price(DATASET, cover, OPTIONS)
        emitted += [*priced.backtest.warnings, *priced.assumptions]

    assert {coded.code for coded in emitted} == set(PRICING_CODES)
    for coded in emitted:
        assert set(coded.params) == PRICING_CODES[coded.code]
        for name, value in coded.params.items():
            assert name.endswith("_rate") == (isinstance(value, str) and bool(RATE.match(value)))
            assert not name.endswith("_cents") or type(value) is int


async def test_warnings_appear_only_when_their_condition_holds() -> None:
    plain = await pricing().backtest(DATASET, builders.cover())
    flagged = await pricing(
        seasons=40, seasons_excluded=(1960, 1951), trend_significant=True
    ).backtest(DATASET, builders.cover())

    assert plain.warnings == []
    assert plain.trend.significant is False
    assert flagged.trend.significant is True
    assert flagged.seasons_excluded == [1951, 1960]
    assert flagged.seasons_used == 38
    assert 1951 not in {season.season for season in flagged.seasons}
    assert flagged.warnings == [
        Coded(
            code="warning.trend_significant",
            params={"slope_per_decade": -12.5, "direction": "decreasing"},
        ),
        Coded(code="warning.seasons_excluded", params={"count": 2, "seasons": "1951, 1960"}),
    ]


async def test_season_series_includes_payouts_only_when_a_limit_is_given() -> None:
    fake = pricing()
    index = builders.cover().index

    without = await fake.season_series(DATASET, index, None)
    with_limit = await fake.season_series(DATASET, index, Money(amount_cents=10_000_000))

    assert all(season.payout is None for season in without.seasons)
    assert all(season.payout is not None for season in with_limit.seasons)
    assert [s.index_value for s in without.seasons] == [s.index_value for s in with_limit.seasons]
    assert (without.dataset_id, without.index) == (DATASET, index)


async def test_extreme_seasons_are_ranked_with_the_empirical_return_period() -> None:
    fake = pricing()
    window = Window(start="10-01", end="03-31")

    seasons = await fake.extreme_seasons(DATASET, "rainfall_below", window, 3)

    assert [season.rank for season in seasons] == [1, 2, 3]
    assert [season.return_period_years for season in seasons] == [31.0, 15.5, 31 / 3]
    for top_n in (0, 11):
        with pytest.raises(InvalidArgumentsError):
            await fake.extreme_seasons(DATASET, "rainfall_below", window, top_n)


async def test_cell_metrics_returns_a_grid_of_the_registered_region() -> None:
    fake = FakePricingFacade()
    area = builders.region("sorriso", nx=3, ny=2)
    fake.add_region(area)
    index: IndexDefinition = builders.cover().index

    frequency = await fake.cell_metrics(
        CellMetricRequest(region_id="sorriso", metric="trigger_frequency", index=index)
    )
    anomaly = await fake.cell_metrics(
        CellMetricRequest(region_id="sorriso", metric="season_anomaly", index=index, season=1998)
    )

    assert (frequency.nx, frequency.ny, len(frequency.values)) == (3, 2, 6)
    assert (frequency.north, frequency.west, frequency.step_deg) == (
        area.north,
        area.west,
        area.step_deg,
    )
    assert all(value is not None and 0 <= value <= 1 for value in frequency.values)
    assert frequency.cells_paying is None
    assert anomaly.cells_paying == 4
    with pytest.raises(InvalidArgumentsError):
        await fake.cell_metrics(
            CellMetricRequest(region_id="sorriso", metric="season_anomaly", index=index)
        )
    with pytest.raises(DatasetNotFoundError):
        await fake.cell_metrics(
            CellMetricRequest(region_id="unknown", metric="trigger_frequency", index=index)
        )


async def test_calls_lists_what_was_received_in_order() -> None:
    fake = pricing()
    cover = builders.cover()

    await fake.backtest(DATASET, cover)
    await fake.price(DATASET, cover, OPTIONS)

    assert fake.calls == [("backtest", (DATASET, cover)), ("price", (DATASET, cover, OPTIONS))]
