"""Ingestion of a point's history: idempotent, keyed by the returned grid point, validated."""

from datetime import UTC, datetime

import numpy as np
import pytest

from tests.unit.climate.fakes import InMemoryPointSource, InMemoryWeatherStore, rain_for, year_days
from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ensure_history import EnsureHistory
from veranico.modules.climate.application.ports import PointFetch
from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.validation import validate_daily
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import OutsideCoverageError
from veranico.shared.kernel.ids import DatasetId, cube_dataset_id, point_dataset_id

FIRST_YEAR = 2018
POINT = (-15.03, -47.93)  # the source answers from the grid point -15.0, -48.0
GRID_POINT = GridPoint(lat=-15.0, lon=-48.0)
DATASET_ID = point_dataset_id(h3_cell_of(GRID_POINT.lat, GRID_POINT.lon))


def at(year: int, month: int = 6, day: int = 15) -> FixedClock:
    return FixedClock(datetime(year, month, day, 9, 0, tzinfo=UTC))


def use_case(
    store: InMemoryWeatherStore, source: InMemoryPointSource, clock: FixedClock
) -> EnsureHistory:
    return EnsureHistory(store, source, clock, first_year=FIRST_YEAR)


@pytest.mark.req("R-4-2", "R-4.2-1")
async def test_the_first_call_fetches_the_first_year_through_the_last_complete_year() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()

    dataset = await use_case(store, source, at(2026))(*POINT)

    assert source.calls == [(*POINT, 2018, 2025)]
    assert dataset == DatasetRef(
        dataset_id=DATASET_ID,
        kind="point",
        region_id=None,
        grid_point=GRID_POINT,
        first_year=2018,
        last_year=2025,
        days=2922,  # eight years, two of them leap years
        missing_days=0,
        source="era5/open-meteo",
    )
    assert store.requests[DATASET_ID] == {"url": "memory://archive", "models": "era5"}


@pytest.mark.req("R-4-2")
async def test_the_current_year_is_never_fetched_even_on_its_last_day() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()

    dataset = await use_case(store, source, at(2026, 12, 31))(*POINT)

    assert dataset.last_year == 2025


@pytest.mark.req("R-4.2-2")
async def test_the_second_call_fetches_nothing() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()
    ensure = use_case(store, source, at(2026))
    first = await ensure(*POINT)

    second = await ensure(*POINT)

    assert second == first
    assert len(source.calls) == 1
    assert store.writes == 1


@pytest.mark.req("R-4.2-2", "R-4.4-1")
async def test_a_store_ending_one_year_short_fetches_only_that_year() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()
    await use_case(store, source, at(2025))(*POINT)  # stores 2018 to 2024
    source.calls.clear()

    dataset = await use_case(store, source, at(2026))(*POINT)

    # The top-up asks for the stored grid point, and only for the missing year.
    assert source.calls == [(GRID_POINT.lat, GRID_POINT.lon, 2025, 2025)]
    assert (dataset.first_year, dataset.last_year, dataset.days) == (2018, 2025, 2922)
    merged = store.series[DATASET_ID]
    assert validate_daily(merged.dates, merged.precipitation_mm) == 0  # no gap, no duplicate
    assert np.array_equal(merged.dates, year_days(2018, 2025))
    assert np.array_equal(merged.precipitation_mm, rain_for(year_days(2018, 2025)))
    assert merged.dates[2556] == np.datetime64("2024-12-31")
    assert merged.dates[2557] == np.datetime64("2025-01-01")


@pytest.mark.req("R-4.2-2")
async def test_a_store_short_on_both_sides_fetches_both_runs_and_merges_in_order() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()
    dates = year_days(2020, 2023)
    store.series[DATASET_ID] = DailySeries(
        dataset=DatasetRef(
            dataset_id=DATASET_ID,
            kind="point",
            region_id=None,
            grid_point=GRID_POINT,
            first_year=2020,
            last_year=2023,
            days=len(dates),
            missing_days=0,
            source="era5/open-meteo",
        ),
        dates=dates,
        precipitation_mm=rain_for(dates),
    )
    store.aliases[h3_cell_of(*POINT)] = DATASET_ID

    dataset = await use_case(store, source, at(2026))(*POINT)

    assert [(first, last) for _, _, first, last in source.calls] == [(2018, 2019), (2024, 2025)]
    assert (dataset.first_year, dataset.last_year) == (2018, 2025)
    merged = store.series[DATASET_ID]
    assert np.array_equal(merged.dates, year_days(2018, 2025))
    assert np.array_equal(merged.precipitation_mm, rain_for(year_days(2018, 2025)))


@pytest.mark.req("R-4.2-1")
async def test_two_clicked_points_with_one_returned_grid_point_share_one_dataset() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()
    ensure = use_case(store, source, at(2026))
    elsewhere = (-14.94, -48.08)  # another H3 cell, the same 0.25 degree grid point
    assert h3_cell_of(*elsewhere) != h3_cell_of(*POINT)

    first = await ensure(*POINT)
    second = await ensure(*elsewhere)

    assert second == first
    assert list(store.series) == [DATASET_ID]
    # The second cell had to ask once to learn its grid point; afterwards it is an alias.
    assert len(source.calls) == 2
    await ensure(*elsewhere)
    assert len(source.calls) == 2


@pytest.mark.req("R-4.4-1")
async def test_invalid_data_writes_nothing() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource(negative_on="2021-03-04")

    with pytest.raises(WeatherDataError, match="negative"):
        await use_case(store, source, at(2026))(*POINT)

    assert store.writes == 0
    assert store.series == {}
    assert store.aliases == {}


@pytest.mark.req("R-4.4-1")
async def test_an_invalid_top_up_keeps_the_stored_series() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource()
    await use_case(store, source, at(2025))(*POINT)
    before = store.series[DATASET_ID]
    source.negative_on = "2025-02-01"

    with pytest.raises(WeatherDataError):
        await use_case(store, source, at(2026))(*POINT)

    assert store.series[DATASET_ID] is before
    assert store.writes == 1


@pytest.mark.req("R-4.4-1")
async def test_an_answer_shorter_than_the_years_asked_is_refused() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource(short_by_days=3)

    with pytest.raises(WeatherDataError, match="whole years"):
        await use_case(store, source, at(2026))(*POINT)

    assert store.writes == 0


async def test_all_missing_data_is_outside_coverage_and_writes_nothing() -> None:
    store, source = InMemoryWeatherStore(), InMemoryPointSource(all_missing=True)

    with pytest.raises(OutsideCoverageError):
        await use_case(store, source, at(2026))(*POINT)

    assert store.writes == 0
    assert store.aliases == {}


async def test_missing_days_are_counted_in_the_dataset() -> None:
    class Patchy(InMemoryPointSource):
        async def fetch(
            self, lat: float, lon: float, first_year: int, last_year: int
        ) -> PointFetch:
            fetched = await super().fetch(lat, lon, first_year, last_year)
            fetched.precipitation_mm[[0, 10, 20]] = np.nan
            return fetched

    store = InMemoryWeatherStore()

    dataset = await use_case(store, Patchy(), at(2026))(*POINT)

    assert dataset.missing_days == 3
    assert dataset.days == 2922


@pytest.mark.req("R-4.4-4")
async def test_a_point_the_store_resolves_to_a_cube_cell_is_answered_without_the_source() -> None:
    cube_cell = DatasetRef(
        dataset_id=cube_dataset_id("sorriso", 3, 4),
        kind="cube",
        region_id="sorriso",
        grid_point=GridPoint(lat=-11.9, lon=-56.3),
        first_year=1950,
        last_year=2020,  # even when the cube ends early, nothing is fetched for it
        days=25933,
        missing_days=0,
        source="synthetic",
    )

    class CubeStore(InMemoryWeatherStore):
        async def locate(self, lat: float, lon: float) -> DatasetId | None:
            return cube_cell.dataset_id

        async def describe(self, dataset_id: DatasetId) -> DatasetRef:
            return cube_cell

    source = InMemoryPointSource()

    dataset = await use_case(CubeStore(), source, at(2026))(-11.93, -56.31)

    assert dataset == cube_cell
    assert source.calls == []
