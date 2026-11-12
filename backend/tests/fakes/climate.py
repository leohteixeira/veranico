"""In-memory fake of `ClimateFacade`: no I/O, deterministic, no more permissive than the contract.

A test registers what exists: `add_series`, `add_cube`, `add_location`, `add_candidates`,
`set_evidence`. `fail_with(error)` makes every later call raise that error (for example
`WeatherSourceUnavailableError`) until `fail_with(None)`. `calls` lists every call received
and `evidence_requests` every `EvidenceRequest`, in order.
"""

from collections.abc import Sequence

from tests.fakes.access import Call
from tests.fakes.builders import cube_cell_ref, h3_cell_for
from veranico.modules.climate.contracts import (
    DailySeries,
    DatasetRef,
    EvidenceRequest,
    Location,
    LocationCandidates,
    Region,
    RegionCube,
)
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    DomainError,
    InvalidArgumentsError,
    LocationNotFoundError,
    OutsideCoverageError,
)
from veranico.shared.kernel.ids import CubeDataset, DatasetId, parse_dataset_id

# Roughly Brazil: south, west, north, east.
COVERAGE = (-34.0, -74.0, 5.5, -34.0)
DEFAULT_EVIDENCE = b"fake-netcdf-evidence"


class FakeClimateFacade:
    def __init__(self) -> None:
        self._series: dict[DatasetId, DailySeries] = {}
        self._by_cell: dict[str, DatasetId] = {}
        self._cubes: dict[str, RegionCube] = {}
        self._names: dict[str, Location | LocationCandidates] = {}
        self._evidence = DEFAULT_EVIDENCE
        self._failure: DomainError | None = None
        self.calls: list[Call] = []
        self.evidence_requests: list[EvidenceRequest] = []

    # What a test registers

    def add_series(self, series: DailySeries) -> DatasetRef:
        """Register a series (it carries only `precipitation_mm`, as the contract type does).

        `ensure_history` at its grid point then returns its dataset.
        """
        dataset = series.dataset
        self._series[dataset.dataset_id] = series
        cell = h3_cell_for(dataset.grid_point.lat, dataset.grid_point.lon)
        self._by_cell[cell] = dataset.dataset_id
        return dataset

    def add_cube(self, cube: RegionCube) -> Region:
        """Register a regional cube; points inside its box resolve to its cells."""
        self._cubes[cube.region.region_id] = cube
        return cube.region

    def with_synthetic_region(
        self, region_id: str, seed: int, *, first_year: int = 2000, last_year: int = 2019
    ) -> Region:
        """Register the full-size (20 by 20) synthetic cube of a showcase region.

        The cube comes from the generator `climate` itself uses for the showcase regions, so a
        consumer's test gets the real shape without importing the module's internals. Twenty
        years by default: the whole history from 1950 takes over a second to generate.
        """
        # The one import of a module's internals in the fakes, kept local to this method.
        from veranico.modules.climate.domain.regions import region_by_id
        from veranico.modules.climate.infrastructure.synthetic import (
            generate_cube,
        )

        definition = region_by_id(region_id)
        if definition is None:
            raise ValueError(f"unknown showcase region: {region_id}")
        return self.add_cube(generate_cube(definition, first_year, last_year, seed))

    def add_location(self, query: str, location: Location) -> None:
        self._names[query.casefold()] = location

    def add_candidates(self, query: str, candidates: Sequence[Location]) -> None:
        """Make a name ambiguous: two to five candidates, as the contract says."""
        if not 2 <= len(candidates) <= 5:
            raise ValueError("an ambiguous name has two to five candidates")
        self._names[query.casefold()] = LocationCandidates(candidates=list(candidates))

    def set_evidence(self, data: bytes) -> None:
        self._evidence = data

    def fail_with(self, error: DomainError | None) -> None:
        self._failure = error

    # ClimateFacade

    async def resolve_location(
        self, query: str | None, lat: float | None, lon: float | None
    ) -> Location | LocationCandidates:
        self._record("resolve_location", query, lat, lon)
        if lat is not None and lon is not None:
            self._check_coverage(lat, lon)
            return Location(
                label=f"{lat:.4f}, {lon:.4f}",
                lat=lat,
                lon=lon,
                h3_cell=h3_cell_for(lat, lon),
                admin_region=None,
                country_code="BR",
            )
        if query is None or lat is not None or lon is not None:
            raise InvalidArgumentsError("give a place name or both coordinates")
        found = self._names.get(query.casefold())
        if found is None:
            raise LocationNotFoundError
        return found

    async def ensure_history(self, lat: float, lon: float) -> DatasetRef:
        self._record("ensure_history", lat, lon)
        self._check_coverage(lat, lon)
        cell = self._cube_cell(lat, lon)
        if cell is not None:
            cube, row, col = cell
            return cube_cell_ref(cube, row, col)
        dataset_id = self._by_cell.get(h3_cell_for(lat, lon))
        if dataset_id is None:
            # The real module would fetch the history. A fake has no source, so this is a
            # mistake in the test's setup and not a domain error.
            raise LookupError(f"no series registered for ({lat}, {lon}): call add_series first")
        return self._series[dataset_id].dataset

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        self._record("describe", dataset_id)
        return self._find(dataset_id).dataset

    async def daily_series(self, dataset_id: DatasetId) -> DailySeries:
        self._record("daily_series", dataset_id)
        return self._find(dataset_id)

    async def regions(self) -> list[Region]:
        self._record("regions")
        return [cube.region for cube in self._cubes.values()]

    async def region_cube(self, region_id: str) -> RegionCube:
        self._record("region_cube", region_id)
        if region_id not in self._cubes:
            raise DatasetNotFoundError
        return self._cubes[region_id]

    async def export_evidence(self, request: EvidenceRequest) -> bytes:
        self._record("export_evidence", request)
        self._find(request.dataset_id)
        self.evidence_requests.append(request)
        return self._evidence

    # Internals

    def _record(self, method: str, *arguments: object) -> None:
        self.calls.append((method, arguments))
        if self._failure is not None:
            raise self._failure

    @staticmethod
    def _check_coverage(lat: float, lon: float) -> None:
        south, west, north, east = COVERAGE
        if not (south <= lat <= north and west <= lon <= east):
            raise OutsideCoverageError

    def _cube_cell(self, lat: float, lon: float) -> tuple[RegionCube, int, int] | None:
        for cube in self._cubes.values():
            area = cube.region
            if area.south < lat <= area.north and area.west <= lon < area.east:
                row = min(int((area.north - lat) / area.step_deg), area.ny - 1)
                col = min(int((lon - area.west) / area.step_deg), area.nx - 1)
                return cube, row, col
        return None

    def _find(self, dataset_id: DatasetId) -> DailySeries:
        if dataset_id in self._series:
            return self._series[dataset_id]
        parsed = parse_dataset_id(dataset_id)
        if isinstance(parsed, CubeDataset) and parsed.region_id in self._cubes:
            cube = self._cubes[parsed.region_id]
            if parsed.row < cube.region.ny and parsed.col < cube.region.nx:
                return DailySeries(
                    dataset=cube_cell_ref(cube, parsed.row, parsed.col),
                    dates=cube.dates,
                    precipitation_mm=cube.precipitation_mm[:, parsed.row, parsed.col],
                )
        raise DatasetNotFoundError
