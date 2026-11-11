"""`WeatherStore` over any storage that can switch a small document atomically.

Everything the two adapters share lives here: the layout (`manifest.py`), validation before
a write, and the atomic write itself (SPEC 4.4). An adapter provides `Storage`: the local
filesystem, or Cloud Storage.

The atomic write. The data is written as a new build under a name no one else uses. Then
the manifest that names it replaces the current one, on the condition that the current one
is still the one that was read: of two writers, one wins and the other learns that it lost.
The build that was replaced is removed afterwards. A reader sees the previous build or the
new one, never a partial store.

Reading. A Zarr store answers a missing chunk with fill values and no error, so a reader
that overlaps the removal of an old build could get a series of missing values. A read
therefore counts only when the manifest still names the same build afterwards; a build is
removed only after the manifest stopped naming it.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import BaseModel
from zarr.abc.store import Store

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

# A writer that keeps losing the manifest switch gives up after this many tries. Each lost
# try means another writer finished in between, so this is only reached under a pile-up.
SWITCH_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class Document:
    text: str
    version: int | None  # the storage's version of the document, when it has one


class Storage(Protocol):
    """What an adapter provides. Paths are the relative paths of `manifest.py`."""

    async def read(self, path: str) -> Document | None:
        """The document, or `None` when it does not exist."""
        ...

    async def switch(self, path: str, text: str, expected: Document | None) -> bool:
        """Replace the document atomically if it is still `expected` (`None`: if it does
        not exist). Return whether it was replaced; `False` means another writer won."""
        ...

    async def put(self, path: str, text: str) -> None:
        """Replace the document atomically, whatever it holds."""
        ...

    async def exists(self, path: str) -> bool: ...

    def zarr(self, build_path: str, *, read_only: bool) -> Path | Store:
        """Where xarray reads or writes the Zarr store of a build."""
        ...

    async def remove_build(self, build_path: str) -> None:
        """Remove a build; a build that does not exist is not an error."""
        ...


class WeatherStoreBusyError(Exception):
    """The manifest switch was lost to other writers too many times in a row."""


class _Head(BaseModel):
    """The fields both manifests have and the switch needs."""

    build: str
    first_date: date
    last_date: date


class ManifestWeatherStore:
    def __init__(self, storage: Storage, clock: Clock) -> None:
        self._storage = storage
        self._clock = clock

    async def locate(self, lat: float, lon: float) -> DatasetId | None:
        region = region_containing(lat, lon)
        if region is not None and await self._storage.exists(cube_manifest_path(region.region_id)):
            return cube_dataset_id(region.region_id, *cell_of(region, lat, lon))
        document = await self._storage.read(alias_path(h3_cell_of(lat, lon)))
        if document is None:
            return None
        return Alias.model_validate_json(document.text).dataset_id

    async def cube_source(self, region_id: str) -> CubeSource | None:
        try:
            return (await self._cube_manifest(region_id)).source
        except DatasetNotFoundError:
            return None

    async def cube_version(self, region_id: str) -> str | None:
        try:
            return (await self._cube_manifest(region_id)).build
        except DatasetNotFoundError:
            return None

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, PointDataset):
            return (await self._point_manifest(parsed.h3_cell)).dataset_ref()
        return _cell_ref(parsed, await self._cube_manifest(parsed.region_id))

    async def describe_cell(self, cell: CubeDataset) -> tuple[DatasetRef, str]:
        manifest = await self._cube_manifest(cell.region_id)
        return _cell_ref(cell, manifest), manifest.build

    async def provenance(self, dataset_id: DatasetId) -> Provenance:
        parsed = parse_dataset_id(dataset_id)
        manifest: PointManifest | CubeManifest
        if isinstance(parsed, PointDataset):
            manifest = await self._point_manifest(parsed.h3_cell)
        else:
            manifest = await self._cube_manifest(parsed.region_id)
            _cell_ref(parsed, manifest)  # an unknown cell has no provenance
        return Provenance(request=manifest.request, checksum=manifest.checksum)

    async def read_series(self, dataset_id: DatasetId) -> DailySeries:
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, PointDataset):
            cell = parsed.h3_cell
            point, (dates, precipitation) = await self._read_current(
                lambda: self._point_manifest(cell),
                lambda manifest: zarr_io.read_series(
                    self._storage.zarr(point_build_path(cell, manifest.build), read_only=True)
                ),
            )
            return DailySeries(
                dataset=point.dataset_ref(), dates=dates, precipitation_mm=precipitation
            )

        async def cube_with_the_cell() -> CubeManifest:
            manifest = await self._cube_manifest(parsed.region_id)
            _cell_ref(parsed, manifest)  # an unknown cell is not found, before any read
            return manifest

        cube, (dates, precipitation) = await self._read_current(
            cube_with_the_cell,
            lambda manifest: zarr_io.read_cell(
                self._storage.zarr(
                    cube_build_path(parsed.region_id, manifest.build), read_only=True
                ),
                parsed.row,
                parsed.col,
            ),
        )
        return DailySeries(
            dataset=_cell_ref(parsed, cube), dates=dates, precipitation_mm=precipitation
        )

    async def read_cube(self, region_id: str) -> RegionCube:
        manifest, (dates, precipitation) = await self._read_current(
            lambda: self._cube_manifest(region_id),
            lambda manifest: zarr_io.read_cube(
                self._storage.zarr(cube_build_path(region_id, manifest.build), read_only=True)
            ),
        )
        return RegionCube(
            region=served_region(_region(region_id), manifest.source),
            dates=dates,
            precipitation_mm=precipitation,
        )

    async def write_point(
        self, series: DailySeries, requested_h3: str, request: Mapping[str, str]
    ) -> None:
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
            request=dict(request),
            checksum=series_checksum(series.dates, series.precipitation_mm),
            written_at=self._clock.now(),
        )
        await self._install(
            point_manifest_path(cell),
            manifest,
            lambda build: point_build_path(cell, build),
            lambda target: zarr_io.write_series(target, series.dates, series.precipitation_mm),
            # Two ingestions of one point fetch the same history: the one that loses the
            # switch is done when the winner already holds its range.
            yield_to_a_covering_winner=True,
        )
        await self._storage.put(
            alias_path(requested_h3), Alias(dataset_id=dataset.dataset_id).model_dump_json(indent=2)
        )

    async def write_cube(self, cube: CubeWrite) -> None:
        region = region_by_id(cube.region_id)
        if region is None:
            raise WeatherDataError(f"unknown region: {cube.region_id}")
        expected = (len(cube.dates), region.ny, region.nx)
        if cube.precipitation_mm.shape != expected:
            raise WeatherDataError(
                f"the cube has shape {cube.precipitation_mm.shape}, the region needs {expected}"
            )
        missing_days = await asyncio.to_thread(validate_cube, cube.dates, cube.precipitation_mm)
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
            checksum=await asyncio.to_thread(series_checksum, cube.dates, cube.precipitation_mm),
            written_at=self._clock.now(),
        )
        latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
        longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
        await self._install(
            cube_manifest_path(region.region_id),
            manifest,
            lambda build: cube_build_path(region.region_id, build),
            lambda target: zarr_io.write_cube(
                target, cube.dates, latitudes, longitudes, cube.precipitation_mm
            ),
            # A cube says where it came from: the last writer's cube must be the current one.
            yield_to_a_covering_winner=False,
        )

    # Internals.

    async def _point_manifest(self, h3_cell: str) -> PointManifest:
        document = await self._storage.read(point_manifest_path(h3_cell))
        if document is None:
            raise DatasetNotFoundError
        return PointManifest.model_validate_json(document.text)

    async def _cube_manifest(self, region_id: str) -> CubeManifest:
        document = await self._storage.read(cube_manifest_path(region_id))
        if document is None:
            raise DatasetNotFoundError
        return CubeManifest.model_validate_json(document.text)

    async def _read_current[M: PointManifest | CubeManifest, T](
        self, current: Callable[[], Awaitable[M]], read: Callable[[M], T]
    ) -> tuple[M, T]:
        """Read the build the current manifest names; return that manifest with the data.

        `read` blocks and runs in a thread.
        """
        manifest = await current()
        while True:
            try:
                data = await asyncio.to_thread(read, manifest)
            except Exception:
                # A writer may have switched the manifest and removed the build that was
                # just named. Then the new manifest names a complete build: read that one.
                newer = await current()
                if newer.build == manifest.build:
                    raise
                manifest = newer
                continue
            newer = await current()
            if newer.build == manifest.build:
                return manifest, data
            manifest = newer  # the build may have been removed during the read: read again

    async def _install(
        self,
        manifest_path: str,
        manifest: PointManifest | CubeManifest,
        build_path: Callable[[str], str],
        write: Callable[[Path | Store], None],
        *,
        yield_to_a_covering_winner: bool,
    ) -> None:
        """Write the build, then make its manifest current. `write` blocks."""
        mine = build_path(manifest.build)
        try:
            await asyncio.to_thread(write, self._storage.zarr(mine, read_only=False))
            replaced = await self._switch(manifest_path, manifest, yield_to_a_covering_winner)
        except BaseException:
            await self._storage.remove_build(mine)
            raise
        if replaced is not None:
            await self._storage.remove_build(build_path(replaced))

    async def _switch(
        self, path: str, manifest: PointManifest | CubeManifest, yield_to_a_covering_winner: bool
    ) -> str | None:
        """Make `manifest` current. Return the build to remove: the one it replaced, or
        its own when it yielded to a winner; `None` when there is nothing to remove."""
        text = manifest.model_dump_json(indent=2)
        lost = False
        for _ in range(SWITCH_ATTEMPTS):
            current = await self._storage.read(path)
            head = None if current is None else _Head.model_validate_json(current.text)
            if (
                lost
                and yield_to_a_covering_winner
                and head is not None
                and head.first_date <= manifest.first_date
                and head.last_date >= manifest.last_date
            ):
                return manifest.build
            if await self._storage.switch(path, text, current):
                return None if head is None else head.build
            lost = True
        raise WeatherStoreBusyError(f"lost the switch of {path} {SWITCH_ATTEMPTS} times")


def _cell_ref(cell: CubeDataset, manifest: CubeManifest) -> DatasetRef:
    try:
        return manifest.cell_ref(_region(cell.region_id), cell.row, cell.col)
    except ValueError:
        raise DatasetNotFoundError from None


def _region(region_id: str) -> RegionDef:
    region = region_by_id(region_id)
    if region is None:
        raise DatasetNotFoundError
    return region
