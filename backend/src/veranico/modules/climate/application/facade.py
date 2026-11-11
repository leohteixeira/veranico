"""The implementation of `ClimateFacade`: thin, it delegates to the use cases and the store."""

import asyncio
from collections import OrderedDict

from veranico.modules.climate.application.ensure_history import EnsureHistory
from veranico.modules.climate.application.export_evidence import ExportEvidence
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.application.resolve_location import ResolveLocation
from veranico.modules.climate.application.served_region import served_region
from veranico.modules.climate.contracts import (
    DailySeries,
    DatasetRef,
    EvidenceRequest,
    Location,
    LocationCandidates,
    Region,
    RegionCube,
)
from veranico.modules.climate.domain.brazil import in_brazil_box
from veranico.modules.climate.domain.regions import REGIONS
from veranico.shared.kernel.errors import DatasetNotFoundError, OutsideCoverageError
from veranico.shared.kernel.ids import DatasetId


class Climate:
    def __init__(
        self,
        store: WeatherStore,
        resolve: ResolveLocation,
        ensure: EnsureHistory,
        export: ExportEvidence,
        cube_cache_size: int,
    ) -> None:
        self._store = store
        self._resolve = resolve
        self._ensure = ensure
        self._export = export
        self._cube_cache_size = cube_cache_size
        self._cubes: OrderedDict[str, tuple[str, RegionCube]] = OrderedDict()
        self._cube_lock = asyncio.Lock()

    async def resolve_location(
        self, query: str | None, lat: float | None, lon: float | None
    ) -> Location | LocationCandidates:
        return await self._resolve(query, lat, lon)

    async def ensure_history(self, lat: float, lon: float) -> DatasetRef:
        if not in_brazil_box(lat, lon):
            raise OutsideCoverageError("the point is outside Brazil")
        return await self._ensure(lat, lon)

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        return await self._store.describe(dataset_id)

    async def daily_series(self, dataset_id: DatasetId) -> DailySeries:
        return await self._store.read_series(dataset_id)

    async def regions(self) -> list[Region]:
        return [
            served_region(definition, await self._store.cube_source(definition.region_id))
            for definition in REGIONS
        ]

    async def region_cube(self, region_id: str) -> RegionCube:
        """The installed cube, decoded once and kept while it is among the most recent.

        A decoded cube of the full history is about 89 MB, so the number kept is small and
        configured. The store's cube version tells a kept cube from a newer build, and
        costs one small read. The lock keeps concurrent first requests from decoding the
        same cube several times at once. The arrays are shared between callers and
        read-only.
        """
        async with self._cube_lock:
            version = await self._store.cube_version(region_id)
            if version is None:
                raise DatasetNotFoundError
            kept = self._cubes.get(region_id)
            if kept is not None and kept[0] == version:
                self._cubes.move_to_end(region_id)
                return kept[1]
            cube = await self._store.read_cube(region_id)
            cube.dates.flags.writeable = False
            cube.precipitation_mm.flags.writeable = False
            self._cubes[region_id] = (version, cube)
            self._cubes.move_to_end(region_id)
            while len(self._cubes) > self._cube_cache_size:
                self._cubes.popitem(last=False)
            return cube

    async def export_evidence(self, request: EvidenceRequest) -> bytes:
        return await self._export(request)
