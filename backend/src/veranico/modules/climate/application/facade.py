"""The implementation of `ClimateFacade`: thin, it delegates to the use cases and the store."""

from veranico.modules.climate.application.ensure_history import EnsureHistory
from veranico.modules.climate.application.export_evidence import ExportEvidence
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.application.resolve_location import ResolveLocation
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
from veranico.modules.climate.domain.regions import REGIONS, RegionDef
from veranico.shared.kernel.errors import DatasetNotFoundError, OutsideCoverageError
from veranico.shared.kernel.ids import DatasetId

REAL_CUBE_SOURCE = "era5-land/cds"


class Climate:
    def __init__(
        self,
        store: WeatherStore,
        resolve: ResolveLocation,
        ensure: EnsureHistory,
        export: ExportEvidence,
    ) -> None:
        self._store = store
        self._resolve = resolve
        self._ensure = ensure
        self._export = export

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
        return [await self._region(definition) for definition in REGIONS]

    async def region_cube(self, region_id: str) -> RegionCube:
        raise DatasetNotFoundError  # no cube can be installed before plan task 9

    async def export_evidence(self, request: EvidenceRequest) -> bytes:
        return await self._export(request)

    async def _region(self, definition: RegionDef) -> Region:
        """The region as served: synthetic unless its installed cube is the real one.

        A region with a synthetic cube and a region with no cube at all both answer
        `synthetic = True`: neither shows real weather history (human gate H1).
        """
        source = await self._store.cube_source(definition.region_id)
        return Region(
            region_id=definition.region_id,
            name=definition.name,
            crop=definition.crop,
            north=definition.north,
            south=definition.south,
            west=definition.west,
            east=definition.east,
            step_deg=definition.step_deg,
            nx=definition.nx,
            ny=definition.ny,
            synthetic=source != REAL_CUBE_SOURCE,
        )
