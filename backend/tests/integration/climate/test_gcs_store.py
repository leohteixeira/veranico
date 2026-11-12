"""`GcsWeatherStore` against the Cloud Storage emulator: the store contract, and the race.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/climate/test_gcs_store.py -m integration -q

The emulator is shared by every agent and test run. Each test works under a prefix of its
own inside one bucket, and nothing here clears the bucket.
"""

import asyncio
import contextlib
import json
import os
import socket
import uuid

import pytest
from google.api_core.exceptions import Conflict

from tests.fakes.settings import settings_for_tests
from tests.integration.climate.store_contract import (
    CLICKED,
    CLOCK,
    GRID_POINT,
    REGION,
    REQUEST,
    InjectedError,
    WeatherStoreContract,
    assert_same_series,
    cube_write,
    point_series,
)
from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.infrastructure.gcs_store import GcsStorage, GcsWeatherStore
from veranico.modules.climate.infrastructure.manifest_store import Document, ManifestWeatherStore
from veranico.modules.climate.module import StoreSettings, store_from_environment
from veranico.shared.infrastructure.blobs import GcsBlobStore, storage_client

pytestmark = pytest.mark.integration

STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
BUCKET = "veranico-climate-tests"


class _FailingSwitch(GcsStorage):
    async def switch(self, path: str, text: str, expected: Document | None) -> bool:
        raise InjectedError


def _require_emulator() -> None:
    host, _, port = STORAGE_HOST.removeprefix("http://").partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Cloud Storage emulator is not listening on {STORAGE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )


def _blobs(bucket: str) -> GcsBlobStore:
    _require_emulator()
    client = storage_client(
        settings_for_tests(
            storage_emulator_host=STORAGE_HOST, storage_bucket=bucket, blob_backend="gcs"
        )
    )
    with contextlib.suppress(Conflict):  # another run created it
        client.create_bucket(bucket)
    return GcsBlobStore(client, bucket)


@pytest.fixture
def blobs() -> GcsBlobStore:
    return _blobs(BUCKET)


@pytest.fixture
def prefix() -> str:
    """A folder no other test uses."""
    return f"t-{uuid.uuid4().hex}/"


@pytest.fixture
def store(blobs: GcsBlobStore, prefix: str) -> GcsWeatherStore:
    return GcsWeatherStore(blobs, BUCKET, STORAGE_HOST, CLOCK, prefix=prefix)


@pytest.fixture
def failing_store(blobs: GcsBlobStore, prefix: str) -> ManifestWeatherStore:
    return ManifestWeatherStore(_FailingSwitch(blobs, BUCKET, STORAGE_HOST, prefix), CLOCK)


class TestGcsWeatherStore(WeatherStoreContract):
    pass


def _point_prefix(prefix: str) -> str:
    return f"{prefix}climate/points/{h3_cell_of(GRID_POINT.lat, GRID_POINT.lon)}/"


def _builds(names: list[str], under: str) -> set[str]:
    """The build names that have at least one object under a dataset's folder."""
    return {name.removeprefix(under).split("/")[0] for name in names if ".zarr/" in name}


@pytest.mark.req("R-4.4-2")
async def test_the_layout_is_the_same_as_on_disk(
    store: GcsWeatherStore, blobs: GcsBlobStore, prefix: str
) -> None:
    series = point_series(2020, 2021)

    await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)

    under = _point_prefix(prefix)
    names = await blobs.list(prefix)
    manifest = json.loads((await blobs.get(f"{under}manifest.json")).data)
    assert f"{prefix}climate/points/aliases/{h3_cell_of(*CLICKED)}.json" in names
    assert _builds(names, under) == {f"{manifest['build']}.zarr"}
    assert f"{under}{manifest['build']}.zarr/precipitation_mm/zarr.json" in names
    assert manifest["dataset_id"] == series.dataset.dataset_id
    assert manifest["written_at"] == "2026-11-11T12:00:00Z"


@pytest.mark.req("R-4.4-2")
async def test_the_previous_build_is_removed_and_a_failed_switch_leaves_no_orphan(
    store: GcsWeatherStore, failing_store: ManifestWeatherStore, blobs: GcsBlobStore, prefix: str
) -> None:
    under = _point_prefix(prefix)
    await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)
    first = _builds(await blobs.list(under), under)

    await store.write_point(point_series(2019, 2022, seed=1), h3_cell_of(*CLICKED), REQUEST)
    second = _builds(await blobs.list(under), under)
    with pytest.raises(InjectedError):
        await failing_store.write_point(
            point_series(2018, 2022, seed=2), h3_cell_of(*CLICKED), REQUEST
        )

    assert len(second) == 1
    assert second != first
    assert _builds(await blobs.list(under), under) == second


@pytest.mark.req("R-4.4-2")
async def test_writers_racing_on_one_point_leave_one_current_build_and_a_readable_store(
    store: GcsWeatherStore, blobs: GcsBlobStore, prefix: str
) -> None:
    # The same range from every writer, as concurrent ingestions of one point produce.
    candidates = [point_series(2018, 2021, seed=seed) for seed in range(4)]

    await asyncio.gather(
        *(store.write_point(series, h3_cell_of(*CLICKED), REQUEST) for series in candidates)
    )

    under = _point_prefix(prefix)
    manifest = json.loads((await blobs.get(f"{under}manifest.json")).data)
    assert _builds(await blobs.list(under), under) == {f"{manifest['build']}.zarr"}
    stored = await store.read_series(candidates[0].dataset.dataset_id)
    winners = [
        series
        for series in candidates
        if (series.precipitation_mm[:5] == stored.precipitation_mm[:5]).all()
    ]
    assert len(winners) == 1
    assert_same_series(stored, winners[0])


@pytest.mark.req("R-4.4-2")
async def test_a_racing_writer_with_a_longer_range_is_not_lost(
    store: GcsWeatherStore, blobs: GcsBlobStore, prefix: str
) -> None:
    short = point_series(2020, 2021, seed=1)
    longer = point_series(2015, 2021, seed=2)

    await asyncio.gather(
        *(store.write_point(series, h3_cell_of(*CLICKED), REQUEST) for series in (short, longer))
    )

    # Whoever switched first, the writer of the longer range does not yield to a manifest
    # that does not cover it. If it switched first, the shorter one replaced it: allowed,
    # because the next ingestion tops the store up; what may not happen is a broken store.
    under = _point_prefix(prefix)
    stored = await store.read_series(short.dataset.dataset_id)
    assert len(_builds(await blobs.list(under), under)) == 1
    assert stored.dataset.first_year in (2015, 2020)
    assert_same_series(stored, longer if stored.dataset.first_year == 2015 else short)


@pytest.mark.req("R-4.1-3")
async def test_a_cube_is_stored_as_four_chunks_under_the_region(
    store: GcsWeatherStore, blobs: GcsBlobStore, prefix: str
) -> None:
    await store.write_cube(cube_write())

    under = f"{prefix}climate/cubes/{REGION.region_id}/"
    names = await blobs.list(under)
    manifest = json.loads((await blobs.get(f"{under}manifest.json")).data)
    chunks = [name for name in names if "/precipitation_mm/c/" in name]
    assert _builds(names, under) == {f"{manifest['build']}.zarr"}
    assert len(chunks) == 4
    assert manifest["chunks"] == {"time": 731, "lat": 10, "lon": 10}


async def test_the_store_built_from_the_environment_reads_what_it_wrote() -> None:
    # The wiring of the scripts has no prefix, so this test takes a bucket of its own.
    bucket = f"veranico-climate-wiring-{uuid.uuid4().hex[:12]}"
    _blobs(bucket)
    settings = StoreSettings(
        climate={"store_backend": "gcs"},
        storage_bucket=bucket,
        storage_emulator_host=STORAGE_HOST,
    )
    series = point_series(2020, 2021)

    await store_from_environment(settings, CLOCK).write_point(series, h3_cell_of(*CLICKED), REQUEST)

    reopened = store_from_environment(settings, CLOCK)
    assert await reopened.locate(*CLICKED) == series.dataset.dataset_id
    assert_same_series(await reopened.read_series(series.dataset.dataset_id), series)
