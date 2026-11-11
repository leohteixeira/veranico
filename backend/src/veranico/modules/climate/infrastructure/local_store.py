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
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import CubeSource, CubeWrite, Provenance
from veranico.modules.climate.application.served_region import served_region
from veranico.modules.climate.contracts import DailySeries, DatasetRef, RegionCube
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import (
    RegionDef,
    cell_centre,
    cell_of,
    region_by_id,
    region_containing,
)
from veranico.modules.climate.domain.validation import validate_cube, validate_daily
from veranico.modules.climate.infrastructure import zarr_io
from veranico.modules.climate.infrastructure.manifest import (
    Alias,
    CubeManifest,
    PointManifest,
    alias_path,
    cube_build_path,
    cube_manifest_path,
    new_build_name,
    point_build_path,
    point_manifest_path,
    series_checksum,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import (
    CubeDataset,
    DatasetId,
    PointDataset,
    cube_dataset_id,
    parse_dataset_id,
)


class _Built(BaseModel):
    """The one field every manifest has: the build it names."""

    build: str


class LocalWeatherStore:
    def __init__(self, root: Path, clock: Clock) -> None:
        self._root = root
        self._clock = clock
        self._switch_lock = threading.Lock()

    async def locate(self, lat: float, lon: float) -> DatasetId | None:
        return await asyncio.to_thread(self._locate, lat, lon)

    async def cube_source(self, region_id: str) -> CubeSource | None:
        return await asyncio.to_thread(self._cube_source, region_id)

    async def cube_version(self, region_id: str) -> str | None:
        return await asyncio.to_thread(self._cube_version, region_id)

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        return await asyncio.to_thread(self._describe, dataset_id)

    async def read_series(self, dataset_id: DatasetId) -> DailySeries:
        return await asyncio.to_thread(self._read_series, dataset_id)

    async def provenance(self, dataset_id: DatasetId) -> Provenance:
        return await asyncio.to_thread(self._provenance, dataset_id)

    async def write_point(
        self, series: DailySeries, requested_h3: str, request: Mapping[str, str]
    ) -> None:
        await asyncio.to_thread(self._write_point, series, requested_h3, dict(request))

    async def read_cube(self, region_id: str) -> RegionCube:
        return await asyncio.to_thread(self._read_cube, region_id)

    async def write_cube(self, cube: CubeWrite) -> None:
        await asyncio.to_thread(self._write_cube, cube)

    # Blocking internals, run in threads.

    def _locate(self, lat: float, lon: float) -> DatasetId | None:
        region = region_containing(lat, lon)
        if region is not None and (self._root / cube_manifest_path(region.region_id)).exists():
            return cube_dataset_id(region.region_id, *cell_of(region, lat, lon))
        try:
            text = (self._root / alias_path(h3_cell_of(lat, lon))).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return Alias.model_validate_json(text).dataset_id

    def _cube_source(self, region_id: str) -> CubeSource | None:
        try:
            return self._cube_manifest(region_id).source
        except DatasetNotFoundError:
            return None

    def _cube_version(self, region_id: str) -> str | None:
        try:
            return self._cube_manifest(region_id).build
        except DatasetNotFoundError:
            return None

    def _describe(self, dataset_id: DatasetId) -> DatasetRef:
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, PointDataset):
            return self._point_manifest(parsed.h3_cell).dataset_ref()
        return self._cell_ref(parsed, self._cube_manifest(parsed.region_id))

    def _provenance(self, dataset_id: DatasetId) -> Provenance:
        parsed = parse_dataset_id(dataset_id)
        manifest: PointManifest | CubeManifest
        if isinstance(parsed, PointDataset):
            manifest = self._point_manifest(parsed.h3_cell)
        else:
            manifest = self._cube_manifest(parsed.region_id)
            self._cell_ref(parsed, manifest)  # an unknown cell has no provenance
        return Provenance(request=manifest.request, checksum=manifest.checksum)

    def _point_manifest(self, h3_cell: str) -> PointManifest:
        try:
            text = (self._root / point_manifest_path(h3_cell)).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DatasetNotFoundError from None
        return PointManifest.model_validate_json(text)

    def _cube_manifest(self, region_id: str) -> CubeManifest:
        try:
            text = (self._root / cube_manifest_path(region_id)).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DatasetNotFoundError from None
        return CubeManifest.model_validate_json(text)

    def _cell_ref(self, cell: CubeDataset, manifest: CubeManifest) -> DatasetRef:
        try:
            return manifest.cell_ref(_region(cell.region_id), cell.row, cell.col)
        except ValueError:
            raise DatasetNotFoundError from None

    def _read_series(self, dataset_id: DatasetId) -> DailySeries:
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, PointDataset):
            cell = parsed.h3_cell
            point, (dates, precipitation) = self._read_current(
                lambda: self._point_manifest(cell),
                lambda manifest: zarr_io.read_series(
                    self._root / point_build_path(cell, manifest.build)
                ),
            )
            return DailySeries(
                dataset=point.dataset_ref(), dates=dates, precipitation_mm=precipitation
            )
        self._cell_ref(parsed, self._cube_manifest(parsed.region_id))  # the cell must exist
        cube, (dates, precipitation) = self._read_current(
            lambda: self._cube_manifest(parsed.region_id),
            lambda manifest: zarr_io.read_cell(
                self._root / cube_build_path(parsed.region_id, manifest.build),
                parsed.row,
                parsed.col,
            ),
        )
        return DailySeries(
            dataset=self._cell_ref(parsed, cube), dates=dates, precipitation_mm=precipitation
        )

    def _read_cube(self, region_id: str) -> RegionCube:
        manifest, (dates, precipitation) = self._read_current(
            lambda: self._cube_manifest(region_id),
            lambda manifest: zarr_io.read_cube(
                self._root / cube_build_path(region_id, manifest.build)
            ),
        )
        return RegionCube(
            region=served_region(_region(region_id), manifest.source),
            dates=dates,
            precipitation_mm=precipitation,
        )

    def _read_current[M: PointManifest | CubeManifest, T](
        self, current: Callable[[], M], read: Callable[[M], T]
    ) -> tuple[M, T]:
        """Read the build the current manifest names; return that manifest with the data."""
        manifest = current()
        while True:
            try:
                return manifest, read(manifest)
            except Exception:
                # A writer may have switched the manifest and removed the build that was
                # just named. Then the new manifest names a complete build: read that one.
                newer = current()
                if newer.build == manifest.build:
                    raise
                manifest = newer

    def _write_point(self, series: DailySeries, requested_h3: str, request: dict[str, str]) -> None:
        missing_days = validate_daily(series.dates, series.precipitation_mm)
        dataset = series.dataset
        parsed = parse_dataset_id(dataset.dataset_id)
        if not isinstance(parsed, PointDataset):
            raise DatasetNotFoundError
        cell = parsed.h3_cell
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

    def _write_cube(self, cube: CubeWrite) -> None:
        region = region_by_id(cube.region_id)
        if region is None:
            raise WeatherDataError(f"unknown region: {cube.region_id}")
        expected = (len(cube.dates), region.ny, region.nx)
        if cube.precipitation_mm.shape != expected:
            raise WeatherDataError(
                f"the cube has shape {cube.precipitation_mm.shape}, the region needs {expected}"
            )
        missing_days = validate_cube(cube.dates, cube.precipitation_mm)
        first, last = cube.dates[0].item(), cube.dates[-1].item()
        days, chunk_lat, chunk_lon = zarr_io.cube_chunks(*expected)
        manifest = CubeManifest(
            region_id=region.region_id,
            build=new_build_name(),
            source=cube.source,
            request=dict(cube.request),
            first_date=first,
            last_date=last,
            days=len(cube.dates),
            years=list(range(first.year, last.year + 1)),
            year_checksums=dict(cube.year_checksums),
            missing_days=missing_days.tolist(),
            chunks={zarr_io.TIME: days, zarr_io.LAT: chunk_lat, zarr_io.LON: chunk_lon},
            checksum=series_checksum(cube.dates, cube.precipitation_mm),
            written_at=self._clock.now(),
        )
        build = self._root / cube_build_path(region.region_id, manifest.build)
        build.parent.mkdir(parents=True, exist_ok=True)
        latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
        longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
        try:
            zarr_io.write_cube(build, cube.dates, latitudes, longitudes, cube.precipitation_mm)
            previous = self._switch_manifest(
                self._root / cube_manifest_path(region.region_id), manifest
            )
        except BaseException:
            shutil.rmtree(build, ignore_errors=True)
            raise
        if previous is not None:
            shutil.rmtree(
                self._root / cube_build_path(region.region_id, previous), ignore_errors=True
            )

    def _switch_manifest(self, path: Path, manifest: PointManifest | CubeManifest) -> str | None:
        """Make `manifest` current and return the build name it replaced, if any."""
        with self._switch_lock:
            try:
                previous = _Built.model_validate_json(path.read_text(encoding="utf-8")).build
            except FileNotFoundError:
                previous = None
            _replace(path, manifest)
            return previous


def _region(region_id: str) -> RegionDef:
    region = region_by_id(region_id)
    if region is None:
        raise DatasetNotFoundError
    return region


def _replace(target: Path, document: BaseModel) -> None:
    """Write to a temporary file in the same directory, then rename over the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)
