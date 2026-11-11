"""The cube path: yearly files, conversion, the local cube store and the module on top."""

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
from veranico.modules.climate.contracts import ClimateFacade, EvidenceRequest, RegionCube
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.infrastructure.cube_build import convert_years, file_checksum
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.synthetic import write_synthetic_cds_year
from veranico.modules.climate.module import assemble
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import DatasetNotFoundError

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
        write_synthetic_cds_year(path, REGION, year, seed=2, south_to_north=year == YEARS[0])
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
    write_synthetic_cds_year(tmp_path / "2023.nc", REGION, 2023, seed=2)

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
