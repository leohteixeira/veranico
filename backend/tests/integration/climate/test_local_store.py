"""`LocalWeatherStore`: the store contract, plus what is specific to the filesystem."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.integration.climate.store_contract import (
    CLICKED,
    CLOCK,
    GRID_POINT,
    REQUEST,
    InjectedError,
    WeatherStoreContract,
    assert_same_series,
    point_series,
)
from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.manifest import PointManifest


class _FailingSwitch(LocalWeatherStore):
    def _switch_manifest(self, path: Path, manifest: PointManifest) -> str | None:
        raise InjectedError


@pytest.fixture
def store(tmp_path: Path) -> LocalWeatherStore:
    return LocalWeatherStore(tmp_path, CLOCK)


@pytest.fixture
def failing_store(tmp_path: Path) -> LocalWeatherStore:
    return _FailingSwitch(tmp_path, CLOCK)


def _point_directory(root: Path) -> Path:
    cell = h3_cell_of(GRID_POINT.lat, GRID_POINT.lon)
    return root / "climate" / "points" / cell


def _builds(root: Path) -> list[str]:
    return sorted(path.name for path in _point_directory(root).glob("*.zarr"))


def _temporary_files(root: Path) -> list[Path]:
    return list(root.rglob("*.tmp"))


class TestLocalWeatherStore(WeatherStoreContract):
    pass


@pytest.mark.req("R-4.2-1")
async def test_layout_is_one_manifest_one_build_and_one_alias(
    store: LocalWeatherStore, tmp_path: Path
) -> None:
    series = point_series(2020, 2021)

    await store.write_point(series, h3_cell_of(*CLICKED), REQUEST)

    manifest = json.loads((_point_directory(tmp_path) / "manifest.json").read_text())
    assert _builds(tmp_path) == [f"{manifest['build']}.zarr"]
    assert manifest["dataset_id"] == series.dataset.dataset_id
    assert manifest["source"] == "era5/open-meteo"
    assert manifest["request"] == REQUEST
    assert manifest["checksum"].startswith("sha256:")
    assert manifest["written_at"] == "2026-11-11T12:00:00Z"
    assert (manifest["first_date"], manifest["last_date"]) == ("2020-01-01", "2021-12-31")
    alias = tmp_path / "climate" / "points" / "aliases" / f"{h3_cell_of(*CLICKED)}.json"
    assert json.loads(alias.read_text()) == {"dataset_id": series.dataset.dataset_id}


@pytest.mark.req("R-4.2-1")
async def test_the_store_is_one_chunk_of_zarr_format_3(
    store: LocalWeatherStore, tmp_path: Path
) -> None:
    await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)

    build = _point_directory(tmp_path) / _builds(tmp_path)[0]
    metadata = json.loads((build / "precipitation_mm" / "zarr.json").read_text())
    assert metadata["zarr_format"] == 3
    assert metadata["shape"] == [731]
    assert metadata["chunk_grid"]["configuration"]["chunk_shape"] == [731]


@pytest.mark.req("R-4.4-2")
async def test_the_previous_build_is_removed_after_the_switch(
    store: LocalWeatherStore, tmp_path: Path
) -> None:
    await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)
    first = _builds(tmp_path)

    await store.write_point(point_series(2019, 2022, seed=1), h3_cell_of(*CLICKED), REQUEST)

    assert len(_builds(tmp_path)) == 1
    assert _builds(tmp_path) != first
    assert not _temporary_files(tmp_path)


@pytest.mark.req("R-4.4-2")
async def test_a_failed_switch_leaves_no_orphan_build(
    store: LocalWeatherStore, failing_store: LocalWeatherStore, tmp_path: Path
) -> None:
    await store.write_point(point_series(2020, 2021), h3_cell_of(*CLICKED), REQUEST)
    first = _builds(tmp_path)

    with pytest.raises(InjectedError):
        await failing_store.write_point(
            point_series(2019, 2022, seed=1), h3_cell_of(*CLICKED), REQUEST
        )

    assert _builds(tmp_path) == first


@pytest.mark.req("R-4.4-2")
async def test_concurrent_writers_leave_one_valid_current_build(
    store: LocalWeatherStore, tmp_path: Path
) -> None:
    candidates = [point_series(2015, 2021, seed=seed) for seed in range(4)]

    await asyncio.gather(
        *(store.write_point(series, h3_cell_of(*CLICKED), REQUEST) for series in candidates)
    )

    assert len(_builds(tmp_path)) == 1
    stored = await store.read_series(candidates[0].dataset.dataset_id)
    winners = [
        series
        for series in candidates
        if (series.precipitation_mm[:5] == stored.precipitation_mm[:5]).all()
    ]
    assert len(winners) == 1
    assert_same_series(stored, winners[0])


async def test_a_second_store_on_the_same_root_reads_what_the_first_wrote(tmp_path: Path) -> None:
    series = point_series(2020, 2021)
    await LocalWeatherStore(tmp_path, CLOCK).write_point(series, h3_cell_of(*CLICKED), REQUEST)

    reopened = LocalWeatherStore(tmp_path, CLOCK)

    assert await reopened.locate(*CLICKED) == series.dataset.dataset_id
    assert_same_series(await reopened.read_series(series.dataset.dataset_id), series)
