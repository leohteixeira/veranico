"""The cube path: yearly files, conversion, the local cube store and the module on top."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import xarray as xr

from tests.fakes.settings import settings_for_tests
from tests.integration.climate.store_contract import (
    CLOCK,
    INSIDE_CELL_ID,
    INSIDE_COL,
    INSIDE_REGION,
    INSIDE_ROW,
    REGION,
    cube_write,
)
from veranico.modules.climate.application.ports import CubeWrite
from veranico.modules.climate.contracts import (
    ClimateFacade,
    DailySeries,
    EvidenceRequest,
    RegionCube,
)
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import REGIONS
from veranico.modules.climate.infrastructure.cube_build import convert_years, file_checksum
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.synthetic import write_synthetic_year
from veranico.modules.climate.module import assemble
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import DatasetId, cube_dataset_id

YEARS = (2020, 2021)
REQUEST = {"dataset": "reanalysis-era5-land", "variable": "total_precipitation"}
# The module's clock: the last complete year is 2021, the last year of the cube.
MODULE_CLOCK = FixedClock(datetime(2022, 5, 10, 12, 0, tzinfo=UTC))


def offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call: {request.url}")


def yearly_files(directory: Path) -> list[Path]:
    """Synthetic yearly files of the whole region, the first one ordered south to north."""
    paths = []
    for year in YEARS:
        path = directory / f"{REGION.region_id}-{year}.nc"
        write_synthetic_year(path, REGION, year, seed=2, south_to_north=year == YEARS[0])
        paths.append(path)
    return paths


def converted(paths: list[Path]) -> CubeWrite:
    cube = convert_years(paths, REGION)
    return CubeWrite(
        region_id=REGION.region_id,
        source="synthetic",
        dates=cube["time"].to_numpy().astype("datetime64[D]"),
        precipitation_mm=cube["precipitation_mm"].to_numpy(),
        request=REQUEST,
        year_checksums={year: file_checksum(path) for year, path in zip(YEARS, paths, strict=True)},
    )


class CountingStore(LocalWeatherStore):
    """Counts the whole-cube reads, which are the expensive ones."""

    cube_reads = 0

    async def read_cube(self, region_id: str) -> RegionCube:
        self.cube_reads += 1
        return await super().read_cube(region_id)


def module_on(store: LocalWeatherStore, *, cube_cache_size: int = 1) -> ClimateFacade:
    settings = settings_for_tests(climate={"first_year": 2020, "cube_cache_size": cube_cache_size})
    http = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    return assemble(settings.climate, MODULE_CLOCK, http, store)


def cube_directory(root: Path) -> Path:
    return root / "climate" / "cubes" / REGION.region_id


def builds(root: Path) -> list[str]:
    return sorted(path.name for path in cube_directory(root).glob("*.zarr"))


@pytest.fixture
def store(tmp_path: Path) -> CountingStore:
    return CountingStore(tmp_path / "weather", CLOCK)


# From yearly files to the stored cube.


@pytest.mark.req("R-4.1-2")
async def test_yearly_files_become_the_stored_cube(store: CountingStore, tmp_path: Path) -> None:
    paths = yearly_files(tmp_path)

    await store.write_cube(converted(paths))

    cube = await store.read_cube(REGION.region_id)
    assert cube.precipitation_mm.shape == (731, 20, 20)
    assert (cube.dates[0], cube.dates[-1]) == (
        np.datetime64("2020-01-01"),
        np.datetime64("2021-12-31"),
    )
    # Cell by cell against the files: metres to millimetres, and row 0 is the northern edge
    # although the first file runs south to north.
    for year, path in zip(YEARS, paths, strict=True):
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            in_file = dataset["tp"].sel(latitude=-11.6, longitude=-56.7, method="nearest")
            north_west = in_file.to_numpy() * 1000.0
        in_year = cube.dates.astype("datetime64[Y]") == np.datetime64(str(year))
        assert np.array_equal(cube.precipitation_mm[in_year, 0, 0], north_west)


@pytest.mark.req("R-4.1-3")
async def test_chunks_hold_the_full_time_axis_by_10_by_10_cells(
    store: CountingStore, tmp_path: Path
) -> None:
    await store.write_cube(cube_write())

    build = cube_directory(tmp_path / "weather") / builds(tmp_path / "weather")[0]
    metadata = json.loads((build / "precipitation_mm" / "zarr.json").read_text())
    assert metadata["zarr_format"] == 3
    assert metadata["shape"] == [731, 20, 20]
    assert metadata["chunk_grid"]["configuration"]["chunk_shape"] == [731, 10, 10]
    assert metadata["data_type"] == "float64"
    chunk_objects = [path for path in (build / "precipitation_mm").rglob("*") if path.is_file()]
    assert len(chunk_objects) == 4 + 1  # four chunks and the array's zarr.json


@pytest.mark.req("R-4.1-5")
async def test_every_manifest_field(store: CountingStore, tmp_path: Path) -> None:
    paths = yearly_files(tmp_path)
    cube = converted(paths)

    await store.write_cube(cube)

    root = tmp_path / "weather"
    manifest = json.loads((cube_directory(root) / "manifest.json").read_text())
    assert set(manifest) == {
        "format_version",
        "region_id",
        "build",
        "source",
        "request",
        "first_date",
        "last_date",
        "days",
        "years",
        "year_checksums",
        "missing_days",
        "chunks",
        "checksum",
        "written_at",
    }
    assert manifest["format_version"] == 1
    assert manifest["region_id"] == "sorriso"
    assert builds(root) == [f"{manifest['build']}.zarr"]
    assert manifest["source"] == "synthetic"
    assert manifest["request"] == REQUEST
    assert (manifest["first_date"], manifest["last_date"]) == ("2020-01-01", "2021-12-31")
    assert manifest["days"] == 731
    assert manifest["years"] == [2020, 2021]
    assert manifest["year_checksums"] == {
        "2020": file_checksum(paths[0]),
        "2021": file_checksum(paths[1]),
    }
    assert manifest["missing_days"] == [[0] * 20 for _ in range(20)]
    assert manifest["chunks"] == {"time": 731, "lat": 10, "lon": 10}
    assert manifest["checksum"].startswith("sha256:")
    assert manifest["written_at"] == "2026-11-11T12:00:00Z"  # from the clock


@pytest.mark.req("R-4.4-1")
async def test_broken_yearly_files_leave_no_manifest(store: CountingStore, tmp_path: Path) -> None:
    paths = yearly_files(tmp_path)
    write_synthetic_year(tmp_path / "2023.nc", REGION, 2023, seed=2)

    with pytest.raises(WeatherDataError, match="missing year"):
        await store.write_cube(converted([*paths, tmp_path / "2023.nc"]))

    assert not cube_directory(tmp_path / "weather").exists()
    assert await store.cube_source(REGION.region_id) is None


@pytest.mark.req("R-4.4-2")
async def test_the_previous_build_is_removed_and_a_failed_one_leaves_nothing(
    store: CountingStore, tmp_path: Path
) -> None:
    root = tmp_path / "weather"
    await store.write_cube(cube_write(seed=1))
    first = builds(root)

    await store.write_cube(cube_write(seed=2))
    second = builds(root)
    broken = cube_write(seed=3)
    broken.precipitation_mm[0, 0, 0] = -1.0
    with pytest.raises(WeatherDataError):
        await store.write_cube(broken)

    assert len(second) == 1
    assert second != first
    assert builds(root) == second
    assert not list(root.rglob("*.tmp"))


# The module on top of the store.


@pytest.mark.req("R-4.4-4")
async def test_ensure_history_inside_the_region_answers_from_the_cube_without_http(
    store: CountingStore,
) -> None:
    await store.write_cube(cube_write())
    climate = module_on(store)  # any HTTP call fails the test

    dataset = await climate.ensure_history(*INSIDE_REGION)

    assert dataset.dataset_id == INSIDE_CELL_ID
    assert (dataset.kind, dataset.region_id, dataset.source) == ("cube", "sorriso", "synthetic")
    assert (dataset.first_year, dataset.last_year, dataset.days) == (2020, 2021, 731)
    assert await climate.describe(INSIDE_CELL_ID) == dataset


@pytest.mark.req("R-4.4-4")
async def test_the_daily_series_of_a_cell_is_that_column_of_the_cube(store: CountingStore) -> None:
    await store.write_cube(cube_write())
    climate = module_on(store)

    cube = await climate.region_cube(REGION.region_id)
    series = await climate.daily_series(INSIDE_CELL_ID)

    assert np.array_equal(series.dates, cube.dates)
    assert np.array_equal(series.precipitation_mm, cube.precipitation_mm[:, INSIDE_ROW, INSIDE_COL])
    assert not np.array_equal(
        series.precipitation_mm, cube.precipitation_mm[:, INSIDE_COL, INSIDE_ROW]
    )


@pytest.mark.req("R-4.1-1")
async def test_region_cube_and_regions_follow_the_source_of_the_installed_cube(
    store: CountingStore,
) -> None:
    climate = module_on(store)
    await store.write_cube(cube_write())

    cube = await climate.region_cube(REGION.region_id)
    assert cube.precipitation_mm.dtype == np.float64
    assert cube.precipitation_mm.shape == (731, 20, 20)
    assert cube.region.synthetic is True
    assert all(region.synthetic for region in await climate.regions())

    await store.write_cube(cube_write(source="era5-land/cds"))

    assert (await climate.region_cube(REGION.region_id)).region.synthetic is False
    synthetic = {region.region_id: region.synthetic for region in await climate.regions()}
    assert synthetic == {"sul-de-minas": True, "sorriso": False, "ribeirao-preto": True}
    assert (await climate.describe(INSIDE_CELL_ID)).source == "era5-land/cds"


async def test_a_cube_is_decoded_once_and_again_only_after_a_new_build(
    store: CountingStore,
) -> None:
    climate = module_on(store)
    await store.write_cube(cube_write(seed=1))

    first = await climate.region_cube(REGION.region_id)
    again = await climate.region_cube(REGION.region_id)

    assert again is first
    assert store.cube_reads == 1
    assert not first.precipitation_mm.flags.writeable  # shared between callers

    await store.write_cube(cube_write(seed=2))
    newer = await climate.region_cube(REGION.region_id)

    assert store.cube_reads == 2
    assert not np.array_equal(newer.precipitation_mm, first.precipitation_mm)


@pytest.mark.parametrize(("cube_cache_size", "reads"), [(1, 3), (2, 2)])
async def test_at_most_the_configured_number_of_cubes_is_kept(
    store: CountingStore, cube_cache_size: int, reads: int
) -> None:
    climate = module_on(store, cube_cache_size=cube_cache_size)
    await store.write_cube(cube_write())
    await store.write_cube(replace(cube_write(seed=4), region_id="sul-de-minas"))

    await climate.region_cube("sorriso")
    await climate.region_cube("sul-de-minas")
    await climate.region_cube("sorriso")  # read again when only one cube is kept

    assert store.cube_reads == reads


# What the load campaign showed (SPEC 16.5): requests rotate over the three regions and
# arrive ten at a time. The bound of five seconds in these tests is not a speed limit: it
# turns a request that waits for another one forever into a failure instead of a hang.


async def test_the_default_keeps_every_showcase_region_so_a_rotation_decodes_each_cube_once(
    store: CountingStore,
) -> None:
    assert ClimateSettings().cube_cache_size == len(REGIONS)
    http = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    climate = assemble(ClimateSettings(first_year=2020), MODULE_CLOCK, http, store)
    for seed, region in enumerate(REGIONS):
        await store.write_cube(replace(cube_write(seed=seed), region_id=region.region_id))

    for _ in range(4):
        for region in REGIONS:
            await climate.region_cube(region.region_id)

    assert store.cube_reads == len(REGIONS)


async def test_concurrent_first_requests_decode_a_cube_once(store: CountingStore) -> None:
    climate = module_on(store)
    await store.write_cube(cube_write())

    cubes = await asyncio.gather(*(climate.region_cube(REGION.region_id) for _ in range(10)))

    assert store.cube_reads == 1
    assert all(cube is cubes[0] for cube in cubes)


class GatedStore(CountingStore):
    """Holds the version read, or the decode, of one region until the test releases it."""

    def __init__(self, root: Path, *, hold_version_of: str = "", hold_decode_of: str = "") -> None:
        super().__init__(root, CLOCK)
        self.hold_version_of = hold_version_of
        self.hold_decode_of = hold_decode_of
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def cube_version(self, region_id: str) -> str | None:
        if region_id == self.hold_version_of:
            self.reached.set()
            await self.release.wait()
        return await super().cube_version(region_id)

    async def read_cube(self, region_id: str) -> RegionCube:
        if region_id == self.hold_decode_of:
            self.reached.set()
            await self.release.wait()
        return await super().read_cube(region_id)


@pytest.mark.parametrize("held", ["hold_version_of", "hold_decode_of"])
async def test_a_kept_cube_is_served_while_another_region_reads_its_version_or_decodes(
    tmp_path: Path, held: str
) -> None:
    store = GatedStore(tmp_path / "weather", **{held: "sul-de-minas"})
    climate = module_on(store, cube_cache_size=3)
    await store.write_cube(cube_write())
    await store.write_cube(replace(cube_write(seed=4), region_id="sul-de-minas"))
    kept = await climate.region_cube("sorriso")

    slow = asyncio.create_task(climate.region_cube("sul-de-minas"))
    await asyncio.wait_for(store.reached.wait(), timeout=5)
    # The other request is now inside its storage read. The kept cube waits for no one.
    served = await asyncio.wait_for(climate.region_cube("sorriso"), timeout=5)

    assert served is kept
    assert not slow.done()
    store.release.set()
    assert (await asyncio.wait_for(slow, timeout=5)).region.region_id == "sul-de-minas"
    assert store.cube_reads == 2


class CellCountingStore(CountingStore):
    """Also counts the reads of a series from the store."""

    series_reads = 0

    async def read_series(self, dataset_id: DatasetId) -> DailySeries:
        self.series_reads += 1
        return await super().read_series(dataset_id)


async def test_a_cell_of_a_kept_cube_is_served_without_a_store_read_and_is_identical(
    tmp_path: Path,
) -> None:
    store = CellCountingStore(tmp_path / "weather", CLOCK)
    climate = module_on(store)
    cube = cube_write()
    cube.precipitation_mm[[3, 9, 200], INSIDE_ROW, INSIDE_COL] = np.nan
    await store.write_cube(cube)
    from_store = await store.read_series(INSIDE_CELL_ID)
    before_the_cube_is_kept = await climate.daily_series(INSIDE_CELL_ID)
    assert (store.series_reads, store.cube_reads) == (2, 0)  # a series never decodes a cube

    kept = await climate.region_cube(REGION.region_id)
    from_cube = await climate.daily_series(INSIDE_CELL_ID)

    assert (store.series_reads, store.cube_reads) == (2, 1)
    for series in (before_the_cube_is_kept, from_cube):
        assert series.dataset == from_store.dataset
        assert series.dates.dtype == from_store.dates.dtype
        assert series.precipitation_mm.dtype == np.float64
        assert np.array_equal(series.dates, from_store.dates)
        # Bit for bit, missing days included.
        assert series.precipitation_mm.tobytes() == from_store.precipitation_mm.tobytes()
    # The caller owns its arrays: changing them does not reach the kept cube.
    assert from_cube.precipitation_mm.flags.writeable
    assert from_cube.precipitation_mm.flags.c_contiguous
    from_cube.precipitation_mm[0] = 123.0
    from_cube.dates[0] = np.datetime64("1900-01-01")
    assert kept.precipitation_mm[0, INSIDE_ROW, INSIDE_COL] != 123.0
    assert kept.dates[0] == np.datetime64("2020-01-01")


async def test_a_cell_is_read_from_the_store_again_once_the_kept_cube_is_stale(
    tmp_path: Path,
) -> None:
    store = CellCountingStore(tmp_path / "weather", CLOCK)
    climate = module_on(store)
    await store.write_cube(cube_write(seed=1))
    await climate.region_cube(REGION.region_id)
    newer = cube_write(seed=2, source="era5-land/cds")
    await store.write_cube(newer)

    series = await climate.daily_series(INSIDE_CELL_ID)

    assert store.series_reads == 1  # the kept cube is of the previous build
    assert series.dataset.source == "era5-land/cds"
    assert np.array_equal(
        series.precipitation_mm, newer.precipitation_mm[:, INSIDE_ROW, INSIDE_COL]
    )


async def test_an_unknown_cell_of_a_kept_cube_is_not_found(store: CountingStore) -> None:
    climate = module_on(store)
    await store.write_cube(cube_write())
    await climate.region_cube(REGION.region_id)

    with pytest.raises(DatasetNotFoundError):
        await climate.daily_series(cube_dataset_id(REGION.region_id, 20, 0))


async def test_region_cube_of_an_unknown_or_uninstalled_region_is_not_found(
    store: CountingStore,
) -> None:
    climate = module_on(store)

    for region_id in ("sorriso", "atlantis", "Not An Id"):
        with pytest.raises(DatasetNotFoundError):
            await climate.region_cube(region_id)
    assert store.cube_reads == 0


@pytest.mark.req("R-4.4-5")
async def test_evidence_of_a_cube_cell_carries_the_provenance_of_the_cube(
    store: CountingStore, tmp_path: Path
) -> None:
    await store.write_cube(cube_write())
    climate = module_on(store)

    evidence = await climate.export_evidence(
        EvidenceRequest(
            dataset_id=INSIDE_CELL_ID,
            window_start="01-01",
            window_end="01-31",
            first_season=2020,
            last_season=2021,
            attributes={},
        )
    )

    target = tmp_path / "evidence.nc"
    target.write_bytes(evidence)
    with xr.open_dataset(target, engine="h5netcdf") as dataset:
        assert dataset.sizes["time"] == 62
        assert dataset.attrs["dataset_id"] == INSIDE_CELL_ID
        assert dataset.attrs["source"] == "synthetic"
        assert json.loads(dataset.attrs["request"]) == {"dataset": "test", "region": "sorriso"}
        assert dataset.attrs["manifest_checksum"].startswith("sha256:")
