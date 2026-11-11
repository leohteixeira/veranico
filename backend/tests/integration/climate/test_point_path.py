"""The point path through the real module: local store on disk, replayed HTTP answers."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest

from tests.fakes.settings import settings_for_tests
from tests.unit.climate.replay import replaying
from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.contracts import ClimateFacade, DatasetRef, GridPoint, Location
from veranico.modules.climate.module import ClimateDeps, build
from veranico.shared.infrastructure.blobs import LocalBlobStore
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import DatasetNotFoundError, OutsideCoverageError
from veranico.shared.kernel.ids import cube_dataset_id, point_dataset_id

# The recording answers exactly this point for 2020 and 2021, so the module is configured
# to want those two years: first year 2020, and a clock in 2022.
CLICKED = (-15.03, -47.93)
GRID_POINT = GridPoint(lat=-15.0, lon=-48.0)
DATASET_ID = point_dataset_id(h3_cell_of(GRID_POINT.lat, GRID_POINT.lon))
CLOCK = FixedClock(datetime(2022, 5, 10, 12, 0, tzinfo=UTC))


def offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call: {request.url}")


def module_on(root: Path, http: httpx.AsyncClient) -> ClimateFacade:
    settings = settings_for_tests(climate={"store_root": root / "weather", "first_year": 2020})
    deps = ClimateDeps(
        settings=settings, clock=CLOCK, http=http, blobs=LocalBlobStore(root / "blobs")
    )
    return build(deps).facade


@pytest.mark.req("R-4.2-1", "R-4.2-2", "R-4.4-4")
async def test_resolve_ensure_describe_and_read_then_a_second_instance_is_offline(
    tmp_path: Path,
) -> None:
    replay = replaying("open_meteo/brasilia_2020_2021.json", "geocoding/sorriso.json")
    climate = module_on(tmp_path, replay.client())

    location = await climate.resolve_location(None, *CLICKED)
    assert isinstance(location, Location)
    assert replay.calls == []  # coordinates resolve without the network

    dataset = await climate.ensure_history(location.lat, location.lon)

    assert dataset == DatasetRef(
        dataset_id=DATASET_ID,
        kind="point",
        region_id=None,
        grid_point=GRID_POINT,
        first_year=2020,
        last_year=2021,
        days=731,
        missing_days=0,
        source="era5/open-meteo",
    )
    assert len(replay.calls) == 1
    assert await climate.describe(DATASET_ID) == dataset
    series = await climate.daily_series(DATASET_ID)
    assert series.dataset == dataset
    assert series.dates[0] == np.datetime64("2020-01-01")
    assert series.dates[-1] == np.datetime64("2021-12-31")
    assert series.precipitation_mm[0] == 3.2  # 2020-01-01 in the recording
    assert series.precipitation_mm[-1] == 14.2  # 2021-12-31

    # A second instance on the same root answers everything without any HTTP call.
    restarted = module_on(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(offline)))
    assert await restarted.ensure_history(*CLICKED) == dataset
    again = await restarted.daily_series(DATASET_ID)
    assert np.array_equal(again.dates, series.dates)
    assert np.array_equal(again.precipitation_mm, series.precipitation_mm)
    assert len(replay.calls) == 1


@pytest.mark.req("R-4.3-1")
async def test_a_place_name_resolves_through_the_module(tmp_path: Path) -> None:
    climate = module_on(tmp_path, replaying("geocoding/sorriso.json").client())

    location = await climate.resolve_location("Sorriso", None, None)

    assert isinstance(location, Location)
    assert (location.label, location.admin_region) == ("Sorriso, MT", "Mato Grosso")


async def test_history_outside_brazil_is_refused_without_the_network(tmp_path: Path) -> None:
    climate = module_on(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(offline)))

    with pytest.raises(OutsideCoverageError):
        await climate.ensure_history(38.72, -9.13)


async def test_unknown_datasets_and_cubes_are_not_found(tmp_path: Path) -> None:
    climate = module_on(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(offline)))

    with pytest.raises(DatasetNotFoundError):
        await climate.describe(DATASET_ID)
    with pytest.raises(DatasetNotFoundError):
        await climate.daily_series(cube_dataset_id("sorriso", 0, 0))
    with pytest.raises(DatasetNotFoundError):
        await climate.region_cube("sorriso")


@pytest.mark.req("R-4.1-1")
async def test_regions_are_synthetic_while_no_real_cube_is_installed(tmp_path: Path) -> None:
    climate = module_on(tmp_path, httpx.AsyncClient(transport=httpx.MockTransport(offline)))

    regions = await climate.regions()

    assert [region.region_id for region in regions] == ["sul-de-minas", "sorriso", "ribeirao-preto"]
    assert all(region.synthetic for region in regions)


def test_the_cloud_storage_weather_store_refuses_local_blobs(tmp_path: Path) -> None:
    # Its manifests are objects of the bucket: with local blobs they would sit on a disk
    # the next instance does not have.
    settings = settings_for_tests(climate={"store_backend": "gcs"})
    deps = ClimateDeps(
        settings=settings,
        clock=CLOCK,
        http=httpx.AsyncClient(transport=httpx.MockTransport(offline)),
        blobs=LocalBlobStore(tmp_path / "blobs"),
    )

    with pytest.raises(ValueError, match="needs VERANICO_BLOB_BACKEND=gcs"):
        build(deps)
