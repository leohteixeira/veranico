"""`WeatherStore` on the local filesystem, for development and tests.

Atomic write (SPEC 4.4): the data is written as a new build directory, then the manifest
that names it replaces the old one by a rename. The previous build is removed afterwards.
A lock makes "read the current manifest, switch, remove the build it named" one step, so
two writers in this process never orphan a build or remove the one that just became
current. Like `LocalBlobStore`, the store is not meant for more than one process.
"""

import asyncio
import os
import shutil
import threading
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.contracts import DailySeries, DatasetRef
from veranico.modules.climate.domain.validation import validate_daily
from veranico.modules.climate.infrastructure import zarr_io
from veranico.modules.climate.infrastructure.manifest import (
    Alias,
    PointManifest,
    alias_path,
    new_build_name,
    point_build_path,
    point_manifest_path,
    series_checksum,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import DatasetId, PointDataset, parse_dataset_id


class LocalWeatherStore:
    def __init__(self, root: Path, clock: Clock) -> None:
        self._root = root
        self._clock = clock
        self._switch_lock = threading.Lock()

    async def locate(self, lat: float, lon: float) -> DatasetId | None:
        return await asyncio.to_thread(self._locate, lat, lon)

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        manifest = await asyncio.to_thread(self._point_manifest, dataset_id)
        return manifest.dataset_ref()

    async def read_series(self, dataset_id: DatasetId) -> DailySeries:
        return await asyncio.to_thread(self._read_series, dataset_id)

    async def write_point(
        self, series: DailySeries, requested_h3: str, request: Mapping[str, str]
    ) -> None:
        await asyncio.to_thread(self._write_point, series, requested_h3, dict(request))

    # Blocking internals, run in threads.

    def _locate(self, lat: float, lon: float) -> DatasetId | None:
        try:
            text = (self._root / alias_path(h3_cell_of(lat, lon))).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return Alias.model_validate_json(text).dataset_id

    def _point_manifest(self, dataset_id: DatasetId) -> PointManifest:
        parsed = parse_dataset_id(dataset_id)
        if not isinstance(parsed, PointDataset):
            raise DatasetNotFoundError
        try:
            text = (self._root / point_manifest_path(parsed.h3_cell)).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DatasetNotFoundError from None
        return PointManifest.model_validate_json(text)

    def _read_series(self, dataset_id: DatasetId) -> DailySeries:
        cell = _point_cell(dataset_id)
        manifest = self._point_manifest(dataset_id)
        while True:
            try:
                dates, precipitation = zarr_io.read_series(
                    self._root / point_build_path(cell, manifest.build)
                )
            except Exception:
                # A writer may have switched the manifest and removed the build that was
                # just named. Then the new manifest names a complete build: read that one.
                current = self._point_manifest(dataset_id)
                if current.build == manifest.build:
                    raise
                manifest = current
                continue
            return DailySeries(
                dataset=manifest.dataset_ref(), dates=dates, precipitation_mm=precipitation
            )

    def _write_point(self, series: DailySeries, requested_h3: str, request: dict[str, str]) -> None:
        missing_days = validate_daily(series.dates, series.precipitation_mm)
        dataset = series.dataset
        cell = _point_cell(dataset.dataset_id)
        manifest = PointManifest(
            dataset_id=dataset.dataset_id,
            build=new_build_name(),
            source=dataset.source,
            grid_point=dataset.grid_point,
            first_date=series.dates[0].item(),
            last_date=series.dates[-1].item(),
            days=len(series.dates),
            missing_days=missing_days,
            request=request,
            checksum=series_checksum(series.dates, series.precipitation_mm),
            written_at=self._clock.now(),
        )
        build = self._root / point_build_path(cell, manifest.build)
        build.parent.mkdir(parents=True, exist_ok=True)
        try:
            zarr_io.write_series(build, series.dates, series.precipitation_mm)
            previous = self._switch_manifest(self._root / point_manifest_path(cell), manifest)
        except BaseException:
            shutil.rmtree(build, ignore_errors=True)
            raise
        if previous is not None:
            shutil.rmtree(self._root / point_build_path(cell, previous), ignore_errors=True)
        _replace(self._root / alias_path(requested_h3), Alias(dataset_id=dataset.dataset_id))

    def _switch_manifest(self, path: Path, manifest: PointManifest) -> str | None:
        """Make `manifest` current and return the build name it replaced, if any."""
        with self._switch_lock:
            try:
                previous = PointManifest.model_validate_json(path.read_text(encoding="utf-8")).build
            except FileNotFoundError:
                previous = None
            _replace(path, manifest)
            return previous


def _point_cell(dataset_id: DatasetId) -> str:
    parsed = parse_dataset_id(dataset_id)
    if not isinstance(parsed, PointDataset):
        raise DatasetNotFoundError
    return parsed.h3_cell


def _replace(target: Path, document: BaseModel) -> None:
    """Write to a temporary file in the same directory, then rename over the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)
