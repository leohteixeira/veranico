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
from veranico.modules.climate.domain.regions import REGIONS, region_by_id
from veranico.shared.kernel.errors import DatasetNotFoundError, OutsideCoverageError
from veranico.shared.kernel.ids import CubeDataset, DatasetId, parse_dataset_id


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
        """The series of a dataset. A cell of a cube that is already kept decoded is
        answered from it: reading the cell from the store decodes a chunk of 100 cells
        (about 22 MB) on every call, which under concurrent quotes takes the threads and
        the processor the other requests need. The values are the same either way; a cube
        is never decoded for a series, so this adds no memory.
        """
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, CubeDataset) and parsed.region_id in self._cubes:
            dataset, version = await self._store.describe_cell(parsed)
            kept = self._cubes.get(parsed.region_id)
            if kept is not None and kept[0] == version:
                cube = kept[1]
                return DailySeries(
                    dataset=dataset,
                    # Copies: the caller owns its arrays, the kept cube stays read-only.
                    dates=cube.dates.copy(),
                    precipitation_mm=cube.precipitation_mm[:, parsed.row, parsed.col].copy(),
                )
        return await self._store.read_series(dataset_id)

    async def regions(self) -> list[Region]:
        return [
            served_region(definition, await self._store.cube_source(definition.region_id))
            for definition in REGIONS
        ]

    async def region_cube(self, region_id: str) -> RegionCube:
        """The installed cube, decoded once and kept while it is among the most recent.

        A decoded cube of the full history is about 89 MB, so the number kept is configured
        (by default the three showcase regions). The store's cube version tells a kept
        cube from a newer build, and costs one small read. That read happens before the
        lock: a request for a kept cube waits for no one. The lock is only for decoding,
        so concurrent first requests do not decode the same cube several times at once.
        The arrays are shared between callers and read-only.
        """
        if region_by_id(region_id) is None:  # also keeps a made-up id out of a storage path
            raise DatasetNotFoundError
        version = await self._store.cube_version(region_id)
        if version is None:
            raise DatasetNotFoundError
        kept = self._cubes.get(region_id)
        if kept is not None and kept[0] == version:
            self._cubes.move_to_end(region_id)
            return kept[1]
        async with self._cube_lock:
            # Whoever held the lock may have decoded this very cube meanwhile.
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
