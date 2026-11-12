"""Behaviour every `WeatherStore` adapter must show, written once.

An adapter's test module subclasses `WeatherStoreContract` and provides two fixtures over
the same storage: `store`, and `failing_store`, whose manifest switch raises
`InjectedError` after the build was written (a crash between the two steps).
"""

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import CubeSource, CubeWrite, WeatherStore
from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import RegionDef, region_by_id
from veranico.modules.climate.infrastructure.synthetic import generate_cube
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import cube_dataset_id, point_dataset_id

CLOCK = FixedClock(datetime(2026, 11, 11, 12, 0, tzinfo=UTC))

# The grid point a source returned, and two clicked points that resolved to it.
GRID_POINT = GridPoint(lat=-15.0, lon=-48.0)
CLICKED = (-15.03, -47.93)
CLICKED_ELSEWHERE = (-14.96, -47.86)
REQUEST = {"url": "https://archive.example/v1/archive?latitude=-15.03&longitude=-47.93"}

# The region the cube tests install, and a point inside it: row 9, column 10, whose centre
# is the grid point -12.5, -55.7.
_SORRISO = region_by_id("sorriso")
assert _SORRISO is not None
REGION: RegionDef = _SORRISO
INSIDE_REGION = (-12.52, -55.68)
INSIDE_ROW, INSIDE_COL = 9, 10
INSIDE_CELL_ID = cube_dataset_id(REGION.region_id, INSIDE_ROW, INSIDE_COL)
CUBE_REQUEST = {"dataset": "test", "region": REGION.region_id}


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


def cube_write(
    *,
    seed: int = 0,
    source: CubeSource = "synthetic",
    first_year: int = 2020,
    last_year: int = 2021,
) -> CubeWrite:
    """A seeded cube of `REGION`; its arrays are fresh, so a test may break them."""
    cube = generate_cube(REGION, first_year, last_year, seed)
    return CubeWrite(
        region_id=REGION.region_id,
        source=source,
        dates=cube.dates,
        precipitation_mm=cube.precipitation_mm,
        request=CUBE_REQUEST,
        year_checksums={year: f"sha256:{year}" for year in range(first_year, last_year + 1)},
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

    # Regional cubes.

    @pytest.mark.req("R-4.1-2")
    async def test_a_cube_round_trip_keeps_dates_and_values_exactly(
        self, store: WeatherStore
    ) -> None:
        cube = cube_write()

        await store.write_cube(cube)

        stored = await store.read_cube(REGION.region_id)
        assert stored.dates.dtype == np.dtype("datetime64[D]")
        assert stored.precipitation_mm.dtype == np.float64
        assert stored.precipitation_mm.shape == (731, 20, 20)
        assert np.array_equal(stored.dates, cube.dates)
        assert np.array_equal(stored.precipitation_mm, cube.precipitation_mm, equal_nan=True)
        assert stored.region.region_id == REGION.region_id
        assert stored.region.synthetic is True
        assert await store.cube_source(REGION.region_id) == "synthetic"

    @pytest.mark.req("R-4.1-1")
    async def test_only_the_real_source_makes_a_region_not_synthetic(
        self, store: WeatherStore
    ) -> None:
        assert await store.cube_source(REGION.region_id) is None

        await store.write_cube(cube_write(source="era5-land/cds"))

        assert await store.cube_source(REGION.region_id) == "era5-land/cds"
        assert (await store.read_cube(REGION.region_id)).region.synthetic is False

    @pytest.mark.req("R-4.4-4")
    async def test_a_point_inside_a_region_with_a_cube_resolves_to_its_cell(
        self, store: WeatherStore
    ) -> None:
        assert await store.locate(*INSIDE_REGION) is None

        await store.write_cube(cube_write())

        assert await store.locate(*INSIDE_REGION) == INSIDE_CELL_ID
        # The neighbouring region has no cube, and a point outside every region none either.
        assert await store.locate(-21.0, -45.5) is None
        assert await store.locate(*CLICKED) is None

    @pytest.mark.req("R-4.4-4")
    async def test_a_cube_cell_is_described_and_read_as_a_dataset(
        self, store: WeatherStore
    ) -> None:
        cube = cube_write()
        cube.precipitation_mm[[3, 9, 200], INSIDE_ROW, INSIDE_COL] = np.nan
        await store.write_cube(cube)

        dataset = await store.describe(INSIDE_CELL_ID)
        series = await store.read_series(INSIDE_CELL_ID)

        assert dataset == DatasetRef(
            dataset_id=INSIDE_CELL_ID,
            kind="cube",
            region_id=REGION.region_id,
            grid_point=GridPoint(lat=-12.5, lon=-55.7),
            first_year=2020,
            last_year=2021,
            days=731,
            missing_days=3,
            source="synthetic",
        )
        assert series.dataset == dataset
        assert np.array_equal(series.dates, cube.dates)
        assert np.array_equal(
            series.precipitation_mm,
            cube.precipitation_mm[:, INSIDE_ROW, INSIDE_COL],
            equal_nan=True,
        )
        assert (await store.describe(cube_dataset_id(REGION.region_id, 0, 0))).missing_days == 0

    async def test_the_provenance_of_a_cube_cell_is_the_request_of_the_cube(
        self, store: WeatherStore
    ) -> None:
        await store.write_cube(cube_write())

        provenance = await store.provenance(INSIDE_CELL_ID)

        assert provenance.request == CUBE_REQUEST
        assert provenance.checksum.startswith("sha256:")

    async def test_unknown_cubes_and_cells_are_not_found(self, store: WeatherStore) -> None:
        with pytest.raises(DatasetNotFoundError):
            await store.read_cube(REGION.region_id)
        with pytest.raises(DatasetNotFoundError):
            await store.describe(INSIDE_CELL_ID)
        await store.write_cube(cube_write())

        for unknown in (
            cube_dataset_id(REGION.region_id, 20, 0),
            cube_dataset_id(REGION.region_id, 0, 20),
            cube_dataset_id("sul-de-minas", 0, 0),
            cube_dataset_id("atlantis", 0, 0),
        ):
            with pytest.raises(DatasetNotFoundError):
                await store.describe(unknown)
            with pytest.raises(DatasetNotFoundError):
                await store.read_series(unknown)
            with pytest.raises(DatasetNotFoundError):
                await store.provenance(unknown)
        with pytest.raises(DatasetNotFoundError):
            await store.read_cube("atlantis")

    @pytest.mark.req("R-4.4-1", "R-4.4-2")
    async def test_a_cube_that_fails_validation_changes_nothing(self, store: WeatherStore) -> None:
        negative = cube_write()
        negative.precipitation_mm[100, 4, 7] = -0.5
        duplicate = cube_write()
        duplicate.dates[50] = duplicate.dates[49]
        wrong_shape = cube_write()
        wrong_shape = replace(wrong_shape, precipitation_mm=wrong_shape.precipitation_mm[:, :10])

        for broken in (negative, duplicate, wrong_shape, replace(cube_write(), region_id="x")):
            with pytest.raises(WeatherDataError):
                await store.write_cube(broken)
        assert await store.cube_source(REGION.region_id) is None
        assert await store.locate(*INSIDE_REGION) is None

        current = cube_write(seed=5)
        await store.write_cube(current)
        with pytest.raises(WeatherDataError):
            await store.write_cube(negative)
        stored = await store.read_cube(REGION.region_id)
        assert np.array_equal(stored.precipitation_mm, current.precipitation_mm)

    @pytest.mark.req("R-4.4-2")
    async def test_a_failure_before_the_cube_manifest_switch_keeps_the_previous_cube(
        self, store: WeatherStore, failing_store: WeatherStore
    ) -> None:
        with pytest.raises(InjectedError):
            await failing_store.write_cube(cube_write())
        assert await store.cube_source(REGION.region_id) is None

        current = cube_write(seed=5)
        await store.write_cube(current)
        with pytest.raises(InjectedError):
            await failing_store.write_cube(cube_write(seed=6, source="era5-land/cds"))

        stored = await store.read_cube(REGION.region_id)
        assert np.array_equal(stored.precipitation_mm, current.precipitation_mm)
        assert await store.cube_source(REGION.region_id) == "synthetic"

    async def test_the_cube_version_changes_with_every_write(self, store: WeatherStore) -> None:
        assert await store.cube_version(REGION.region_id) is None

        await store.write_cube(cube_write())
        first = await store.cube_version(REGION.region_id)
        await store.write_cube(cube_write())  # the same data again is still a new build

        assert first is not None
        assert await store.cube_version(REGION.region_id) not in (None, first)

    async def test_a_second_cube_replaces_the_first(self, store: WeatherStore) -> None:
        await store.write_cube(cube_write(seed=5))
        longer = cube_write(seed=6, first_year=2019, last_year=2021)

        await store.write_cube(longer)

        stored = await store.read_cube(REGION.region_id)
        assert np.array_equal(stored.dates, longer.dates)
        assert np.array_equal(stored.precipitation_mm, longer.precipitation_mm)
        assert (await store.describe(INSIDE_CELL_ID)).first_year == 2019
