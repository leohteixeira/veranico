"""In-memory ports for the climate unit tests: a point source and a weather store.

Both are deterministic and do no I/O. The store keeps the rules of the port: it validates
before it writes, an unknown dataset is `dataset_not_found`, and a clicked cell becomes an
alias of the dataset it was written with.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import CubeSource, PointFetch, Provenance
from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.modules.climate.domain.validation import validate_daily
from veranico.shared.kernel.errors import DatasetNotFoundError
from veranico.shared.kernel.ids import DatasetId

FAKE_CHECKSUM = "sha256:in-memory"


def year_days(first_year: int, last_year: int) -> np.ndarray:
    return np.arange(f"{first_year}-01-01", f"{last_year + 1}-01-01", dtype="datetime64[D]")


def rain_for(dates: np.ndarray) -> np.ndarray:
    """A deterministic value per calendar day, so separate fetches of one day agree."""
    day_number = dates.astype("datetime64[D]").astype(np.int64)
    return (day_number % 17).astype(np.float64) * 1.5


@dataclass
class InMemoryPointSource:
    """Answers from one grid point (a 0.25 degree grid by default) and counts its calls."""

    grid_step: float = 0.25
    all_missing: bool = False
    negative_on: str | None = None  # ISO date that gets an invalid, negative value
    short_by_days: int = 0  # drop this many days from the end of every answer
    calls: list[tuple[float, float, int, int]] = field(default_factory=list)

    def grid_point(self, lat: float, lon: float) -> GridPoint:
        steps = 1 / self.grid_step
        return GridPoint(
            lat=float(np.floor(lat * steps + 0.5) / steps),
            lon=float(np.floor(lon * steps + 0.5) / steps),
        )

    async def fetch(self, lat: float, lon: float, first_year: int, last_year: int) -> PointFetch:
        self.calls.append((lat, lon, first_year, last_year))
        dates = year_days(first_year, last_year)
        rain = rain_for(dates)
        if self.all_missing:
            rain[:] = np.nan
        if self.negative_on is not None:
            rain[dates == np.datetime64(self.negative_on)] = -1.0
        if self.short_by_days:
            dates, rain = dates[: -self.short_by_days], rain[: -self.short_by_days]
        return PointFetch(
            grid_point=self.grid_point(lat, lon),
            dates=dates,
            precipitation_mm=rain,
            source="era5/open-meteo",
            request={"url": "memory://archive", "models": "era5"},
            attempts=1,
        )


@dataclass
class InMemoryWeatherStore:
    series: dict[DatasetId, DailySeries] = field(default_factory=dict)
    aliases: dict[str, DatasetId] = field(default_factory=dict)
    requests: dict[DatasetId, dict[str, str]] = field(default_factory=dict)
    writes: int = 0
    cube_sources: dict[str, CubeSource] = field(default_factory=dict)

    async def locate(self, lat: float, lon: float) -> DatasetId | None:
        return self.aliases.get(h3_cell_of(lat, lon))

    async def cube_source(self, region_id: str) -> CubeSource | None:
        return self.cube_sources.get(region_id)

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        return (await self.read_series(dataset_id)).dataset

    async def read_series(self, dataset_id: DatasetId) -> DailySeries:
        if dataset_id not in self.series:
            raise DatasetNotFoundError
        return self.series[dataset_id]

    async def provenance(self, dataset_id: DatasetId) -> Provenance:
        await self.read_series(dataset_id)
        return Provenance(request=self.requests.get(dataset_id, {}), checksum=FAKE_CHECKSUM)

    async def write_point(
        self, series: DailySeries, requested_h3: str, request: Mapping[str, str]
    ) -> None:
        validate_daily(series.dates, series.precipitation_mm)
        self.writes += 1
        self.series[series.dataset.dataset_id] = series
        self.requests[series.dataset.dataset_id] = dict(request)
        self.aliases[requested_h3] = series.dataset.dataset_id
