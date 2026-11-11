"""Behaviour every `WeatherStore` adapter must show, written once.

An adapter's test module subclasses `WeatherStoreContract` and provides two fixtures over
the same storage: `store`, and `failing_store`, whose manifest switch raises
`InjectedError` after the build was written (a crash between the two steps).
"""

from datetime import UTC, datetime

import numpy as np
import pytest

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import point_dataset_id

CLOCK = FixedClock(datetime(2026, 11, 11, 12, 0, tzinfo=UTC))

# The grid point a source returned, and two clicked points that resolved to it.
GRID_POINT = GridPoint(lat=-15.0, lon=-48.0)
CLICKED = (-15.03, -47.93)
CLICKED_ELSEWHERE = (-14.96, -47.86)
REQUEST = {"url": "https://archive.example/v1/archive?latitude=-15.03&longitude=-47.93"}


class InjectedError(Exception):
    """Raised by `failing_store` in place of the manifest switch."""


def point_series(first_year: int, last_year: int, *, seed: int = 0) -> DailySeries:
    """A seeded daily series at `GRID_POINT` with a few missing days."""
    dates = np.arange(f"{first_year}-01-01", f"{last_year + 1}-01-01", dtype="datetime64[D]")
    rain = np.random.default_rng(seed).gamma(0.6, 9.0, len(dates))
    rain[[5, 40]] = np.nan
    return DailySeries(
        dataset=DatasetRef(
            dataset_id=point_dataset_id(h3_cell_of(GRID_POINT.lat, GRID_POINT.lon)),
            kind="point",
            region_id=None,
            grid_point=GRID_POINT,
            first_year=first_year,
            last_year=last_year,
            days=len(dates),
            missing_days=2,
            source="era5/open-meteo",
        ),
        dates=dates,
        precipitation_mm=rain,
    )


def assert_same_series(actual: DailySeries, expected: DailySeries) -> None:
    assert actual.dates.dtype == np.dtype("datetime64[D]")
    assert actual.precipitation_mm.dtype == np.float64
    assert np.array_equal(actual.dates, expected.dates)
    assert np.array_equal(actual.precipitation_mm, expected.precipitation_mm, equal_nan=True)
    assert actual.dataset == expected.dataset


class WeatherStoreContract:
    @pytest.mark.req("R-4.2-1")
    async def test_round_trip_keeps_dates_and_values_exactly(self, store: WeatherStore) -> None:
        series = point_series(2020, 2021)

        await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)

        dataset_id = series.dataset.dataset_id
        assert_same_series(await store.read_series(dataset_id), series)
        assert await store.describe(dataset_id) == series.dataset

    async def test_describe_is_computed_from_the_data(self, store: WeatherStore) -> None:
        series = point_series(2020, 2021)
        wrong = series.dataset.model_copy(update={"days": 1, "missing_days": 0, "first_year": 1})

        await store.write_point(
            DailySeries(
                dataset=wrong, dates=series.dates, precipitation_mm=series.precipitation_mm
            ),
            h3_cell_of(*CLICKED),
            REQUEST,
        )

        assert await store.describe(series.dataset.dataset_id) == series.dataset

    @pytest.mark.req("R-4.2-1")
    async def test_locate_returns_the_dataset_through_the_alias(self, store: WeatherStore) -> None:
        series = point_series(2020, 2021)
        await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)
        await store.write_point(series, h3_cell_of(*CLICKED_ELSEWHERE), REQUEST)

        # Two clicked cells, one returned grid point: one dataset.
        assert h3_cell_of(*CLICKED) != h3_cell_of(*CLICKED_ELSEWHERE)
        assert await store.locate(*CLICKED) == series.dataset.dataset_id
        assert await store.locate(*CLICKED_ELSEWHERE) == series.dataset.dataset_id

    async def test_locate_is_none_for_an_unknown_cell(self, store: WeatherStore) -> None:
        await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)

        assert await store.locate(-3.1, -60.0) is None

    async def test_an_unknown_dataset_is_not_found(self, store: WeatherStore) -> None:
        unknown = point_dataset_id(h3_cell_of(-3.1, -60.0))

        with pytest.raises(DatasetNotFoundError):
            await store.describe(unknown)
        with pytest.raises(DatasetNotFoundError):
            await store.read_series(unknown)

    async def test_a_second_write_replaces_the_series(self, store: WeatherStore) -> None:
        await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)
        longer = point_series(2019, 2022, seed=1)

        await store.write_point(longer, h3_cell_of(*CLICKED), REQUEST)

        assert_same_series(await store.read_series(longer.dataset.dataset_id), longer)

    @pytest.mark.req("R-4.4-1", "R-4.4-2")
    async def test_a_write_that_fails_validation_leaves_the_previous_build_readable(
        self, store: WeatherStore
    ) -> None:
        series = point_series(2020, 2021)
        await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)
        broken = point_series(2020, 2022, seed=1)
        broken.precipitation_mm[10] = -1.0

        with pytest.raises(WeatherDataError):
            await store.write_point(broken, h3_cell_of(*CLICKED), REQUEST)

        assert_same_series(await store.read_series(series.dataset.dataset_id), series)

    @pytest.mark.req("R-4.4-1")
    async def test_a_first_write_that_fails_validation_writes_nothing(
        self, store: WeatherStore
    ) -> None:
        broken = point_series(2020, 2021)
        dates = broken.dates.copy()
        dates[3] = dates[2]  # a duplicate date, and so a gap after it

        with pytest.raises(WeatherDataError):
            await store.write_point(
                DailySeries(
                    dataset=broken.dataset, dates=dates, precipitation_mm=broken.precipitation_mm
                ),
                h3_cell_of(*CLICKED),
                REQUEST,
            )

        with pytest.raises(DatasetNotFoundError):
            await store.describe(broken.dataset.dataset_id)
        assert await store.locate(*CLICKED) is None

    @pytest.mark.req("R-4.4-2")
    async def test_a_failure_before_the_manifest_switch_keeps_the_previous_build_current(
        self, store: WeatherStore, failing_store: WeatherStore
    ) -> None:
        series = point_series(2020, 2021)
        await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)

        with pytest.raises(InjectedError):
            await failing_store.write_point(
                point_series(2019, 2022, seed=1), h3_cell_of(*CLICKED_ELSEWHERE), REQUEST
            )

        assert_same_series(await store.read_series(series.dataset.dataset_id), series)
        assert await store.describe(series.dataset.dataset_id) == series.dataset
        assert await store.locate(*CLICKED_ELSEWHERE) is None

    @pytest.mark.req("R-4.4-2")
    async def test_a_failure_before_the_first_manifest_leaves_no_dataset(
        self, store: WeatherStore, failing_store: WeatherStore
    ) -> None:
        series = point_series(2020, 2021)

        with pytest.raises(InjectedError):
            await failing_store.write_point(series, h3_cell_of(*CLICKED), REQUEST)

        with pytest.raises(DatasetNotFoundError):
            await store.read_series(series.dataset.dataset_id)
        assert await store.locate(*CLICKED) is None
