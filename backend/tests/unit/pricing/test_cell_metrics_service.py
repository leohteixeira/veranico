"""`PricingFacade.cell_metrics` over `FakeClimateFacade`: the grid, the cache, the errors."""

from typing import Any

import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from tests.unit.pricing import cells_fixture as fixture
from veranico.modules.climate.contracts import RegionCube
from veranico.modules.pricing.application.cell_cache import CellCache
from veranico.modules.pricing.application.service import PricingService
from veranico.modules.pricing.contracts import (
    CellGrid,
    CellMetricRequest,
    IndexDefinition,
    Window,
)
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    InsufficientHistoryError,
    InvalidArgumentsError,
    InvalidCoverError,
)

REGION_ID = "sorriso"
RAINFALL = IndexDefinition(
    index_type="rainfall_below",
    window=Window(start=fixture.WINDOW[0], end=fixture.WINDOW[1]),
    trigger=35.0,
    exit=5.0,
)
DRY_SPELL = IndexDefinition(
    index_type="dry_spell_above",
    window=Window(start=fixture.WINDOW[0], end=fixture.WINDOW[1]),
    trigger=2.0,
    exit=5.0,
)


def hand_cube() -> RegionCube:
    """The 2 by 2 cube of `cells_fixture.py` as the region `sorriso`."""
    dates, rain = fixture.cube()
    return RegionCube(region=builders.region(REGION_ID), dates=dates, precipitation_mm=rain)


def service_over(cube: RegionCube, **pricing: Any) -> tuple[PricingService, FakeClimateFacade]:
    climate = FakeClimateFacade()
    climate.add_cube(cube)
    settings = settings_for_tests(pricing=pricing)
    return PricingService(climate=climate, settings=settings.pricing), climate


def hand_service(**pricing: Any) -> tuple[PricingService, FakeClimateFacade]:
    """Four seasons only, so the minimum is lowered to four unless a test sets it."""
    return service_over(hand_cube(), **{"min_seasons": 4, **pricing})


def frequency(index: IndexDefinition = RAINFALL, season: int | None = None) -> CellMetricRequest:
    return CellMetricRequest(
        region_id=REGION_ID, metric="trigger_frequency", index=index, season=season
    )


def anomaly(season: int | None, index: IndexDefinition = RAINFALL) -> CellMetricRequest:
    return CellMetricRequest(
        region_id=REGION_ID, metric="season_anomaly", index=index, season=season
    )


def cube_reads(climate: FakeClimateFacade) -> int:
    return sum(1 for name, _ in climate.calls if name == "region_cube")


@pytest.mark.req("R-5.8-1")
@pytest.mark.req("R-5.8-3")
async def test_trigger_frequency_grid_is_row_major_from_the_north_west() -> None:
    service, _ = hand_service()

    grid = await service.cell_metrics(frequency())

    area = builders.region(REGION_ID)
    assert grid == CellGrid(
        region_id=REGION_ID,
        metric="trigger_frequency",
        nx=2,
        ny=2,
        north=area.north,
        west=area.west,
        step_deg=area.step_deg,
        values=[0.75, 1.0, 0.25, 0.666667],  # A, B (north), then C, D
        breaks=[0.25, 0.4, 0.55, 0.7, 0.85, 1.0],
        seasons=[2001, 2002, 2003, 2004],
        cells_paying=None,
        suggested_season=2004,
    )


@pytest.mark.req("R-5.8-1")
async def test_trigger_frequency_grid_of_dry_spells() -> None:
    service, _ = hand_service()

    grid = await service.cell_metrics(frequency(DRY_SPELL))

    assert grid.values == [0.25, 1.0, 0.0, 0.333333]
    assert grid.breaks == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert grid.cells_paying is None


@pytest.mark.req("R-5.8-2")
@pytest.mark.req("R-5.8-3")
@pytest.mark.req("R-5.8-4")
async def test_season_anomaly_grid_carries_none_breaks_and_the_paying_cells() -> None:
    service, _ = hand_service()

    grid = await service.cell_metrics(anomaly(2003))

    assert grid.metric == "season_anomaly"
    assert grid.values == [-0.2, None, -0.328, -0.5]  # B has a median of zero
    assert grid.breaks == [-0.5, -0.333333, -0.166667, 0.0, 0.166667, 0.333333, 0.5]
    assert grid.cells_paying == 4
    assert grid.seasons == [2001, 2002, 2003, 2004]


@pytest.mark.req("R-5.8-2")
@pytest.mark.req("R-5.8-4")
async def test_cell_without_a_value_in_the_season_is_none_and_does_not_pay() -> None:
    service, _ = hand_service()

    grid = await service.cell_metrics(anomaly(2002))

    assert grid.values == [0.2, None, 0.2, None]  # D has a missing day in 2002
    assert grid.cells_paying == 2


@pytest.mark.req("R-12.2-4")
async def test_suggested_season_is_returned_for_both_metrics() -> None:
    service, _ = hand_service()

    assert (await service.cell_metrics(frequency())).suggested_season == 2004
    assert (await service.cell_metrics(anomaly(2001))).suggested_season == 2004


@pytest.mark.req("R-5.8-5")
async def test_second_identical_request_does_not_read_the_cube_again() -> None:
    service, climate = hand_service()

    first = await service.cell_metrics(anomaly(2003))
    second = await service.cell_metrics(anomaly(2003))

    assert second == first
    assert cube_reads(climate) == 1


@pytest.mark.req("R-5.8-5")
async def test_cache_is_keyed_by_region_index_definition_and_season() -> None:
    service, climate = hand_service()

    await service.cell_metrics(anomaly(2003))
    await service.cell_metrics(anomaly(2004))  # another season
    await service.cell_metrics(anomaly(2003, DRY_SPELL))  # another index definition
    await service.cell_metrics(frequency())  # another metric

    assert cube_reads(climate) == 4
    assert len(service.cell_cache) == 4


@pytest.mark.req("R-5.8-5")
async def test_trigger_frequency_ignores_the_season_and_shares_one_entry() -> None:
    service, climate = hand_service()

    without = await service.cell_metrics(frequency())
    with_season = await service.cell_metrics(frequency(season=2003))

    assert with_season == without
    assert cube_reads(climate) == 1
    assert len(service.cell_cache) == 1


@pytest.mark.req("R-5.8-5")
async def test_cache_never_exceeds_its_bound_and_evicts_the_least_recently_used() -> None:
    service, climate = hand_service(cell_cache_entries=2)

    await service.cell_metrics(anomaly(2001))
    await service.cell_metrics(anomaly(2002))
    await service.cell_metrics(anomaly(2001))  # a hit: 2001 is now the most recent
    await service.cell_metrics(anomaly(2003))  # evicts 2002
    assert len(service.cell_cache) == 2
    assert cube_reads(climate) == 3

    await service.cell_metrics(anomaly(2001))  # still cached
    assert cube_reads(climate) == 3
    await service.cell_metrics(anomaly(2002))  # was evicted: computed again
    assert cube_reads(climate) == 4
    assert len(service.cell_cache) == 2


@pytest.mark.req("R-5.8-5")
def test_cell_cache_holds_at_most_its_bound() -> None:
    cache = CellCache(3)
    grid = CellGrid(
        region_id=REGION_ID,
        metric="trigger_frequency",
        nx=1,
        ny=1,
        north=0.0,
        west=0.0,
        step_deg=0.1,
        values=[0.5],
        breaks=[0.5, 0.5],
        seasons=[2000],
        cells_paying=None,
        suggested_season=2000,
    )

    for key in range(50):
        cache.put(key, grid)
        assert len(cache) <= 3

    assert [cache.get(key) is not None for key in (46, 47, 48, 49)] == [False, True, True, True]
    with pytest.raises(ValueError, match="at least one"):
        CellCache(0)


@pytest.mark.req("R-5-1")
@pytest.mark.req("R-5.8-5")
async def test_results_are_deterministic_across_services() -> None:
    cube = builders.region_cube(seed=3, nx=20, ny=20)
    index = IndexDefinition(
        index_type="dry_spell_above",
        window=Window(start="11-15", end="02-15"),
        trigger=8.0,
        exit=16.0,
    )
    request = CellMetricRequest(region_id="sorriso", metric="trigger_frequency", index=index)
    first_service, _ = service_over(cube)
    second_service, _ = service_over(cube)

    first = await first_service.cell_metrics(request)
    second = await second_service.cell_metrics(request)

    assert first == second
    assert (first.nx, first.ny) == (20, 20)
    assert len(first.values) == 400
    assert all(value is not None and 0.0 <= value <= 1.0 for value in first.values)
    assert first.seasons == list(range(1950, 2024))  # the window crosses the year
    assert first.suggested_season in first.seasons
    assert first.breaks == sorted(first.breaks)
    assert len(first.breaks) == 6


@pytest.mark.req("R-5.3-3")
@pytest.mark.parametrize(
    "index",
    [
        RAINFALL.model_copy(update={"exit": 50.0}),  # exit above the trigger
        DRY_SPELL.model_copy(update={"exit": 1.0}),  # exit below the trigger
        RAINFALL.model_copy(update={"window": Window(start="02-30", end="03-10")}),
    ],
)
async def test_bad_index_is_an_invalid_cover_and_reads_no_cube(index: IndexDefinition) -> None:
    service, climate = hand_service()

    with pytest.raises(InvalidCoverError):
        await service.cell_metrics(frequency(index))
    assert climate.calls == []


async def test_season_anomaly_without_a_season_is_invalid_arguments() -> None:
    service, climate = hand_service()

    with pytest.raises(InvalidArgumentsError):
        await service.cell_metrics(anomaly(None))
    assert climate.calls == []


@pytest.mark.parametrize("season", [2000, 2005, 1950])
async def test_season_anomaly_of_a_season_not_in_the_list_is_invalid_arguments(
    season: int,
) -> None:
    service, _ = hand_service()

    with pytest.raises(InvalidArgumentsError):
        await service.cell_metrics(anomaly(season))
    assert len(service.cell_cache) == 0  # a failure is not cached


async def test_fewer_seasons_than_the_minimum_is_insufficient_history() -> None:
    service, _ = service_over(hand_cube())  # four seasons against the default minimum of 20

    with pytest.raises(InsufficientHistoryError):
        await service.cell_metrics(frequency())


async def test_unknown_region_passes_dataset_not_found_through() -> None:
    service, _ = hand_service()
    request = CellMetricRequest(region_id="nowhere", metric="trigger_frequency", index=RAINFALL)

    with pytest.raises(DatasetNotFoundError):
        await service.cell_metrics(request)
