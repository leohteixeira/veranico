"""Ports of the climate application layer; the adapters live in `infrastructure/`."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from veranico.modules.climate.contracts import DailySeries, DatasetRef, GridPoint
from veranico.shared.kernel.ids import DatasetId

CubeSource = Literal["era5-land/cds", "synthetic"]


@dataclass(frozen=True, slots=True)
class PointFetch:
    """What a point source returned for a range of whole years."""

    grid_point: GridPoint  # of the grid cell the source used, not the requested point
    dates: np.ndarray  # datetime64[D], every day of the requested years, ascending
    precipitation_mm: np.ndarray  # float64; NaN where the source has no value
    source: Literal["era5/open-meteo"]  # the product the values come from (ADR 0017)
    request: Mapping[str, str]  # what was asked, kept as provenance
    attempts: int  # HTTP attempts made, retries included


@dataclass(frozen=True, slots=True)
class GeocodeHit:
    """A populated place a geocoder found for a name."""

    name: str
    lat: float
    lon: float
    admin1: str | None  # first-level administrative area: in Brazil, the state
    country_code: str  # ISO 3166-1 alpha-2


class Geocoder(Protocol):
    async def search(self, name: str) -> list[GeocodeHit]:
        """Places matching a name, best match first; empty when nothing matches.

        Raises `WeatherSourceUnavailableError` when the geocoder cannot be reached.
        """
        ...


class PointSource(Protocol):
    async def fetch(self, lat: float, lon: float, first_year: int, last_year: int) -> PointFetch:
        """Daily precipitation sums by local day for the years `first_year` to `last_year`.

        Raises `WeatherSourceUnavailableError` when the source cannot be reached.
        """
        ...


class WeatherStore(Protocol):
    """Where validated weather data lives (SPEC 4.4): on disk or on Cloud Storage.

    A dataset that does not exist raises `DatasetNotFoundError`. A write validates first
    and is atomic: a reader sees the previous data or the new data, never a partial store.
    """

    async def locate(self, lat: float, lon: float) -> DatasetId | None:
        """The stored dataset a point resolves to, without any network call."""
        ...

    async def cube_source(self, region_id: str) -> CubeSource | None:
        """The source of the region's installed cube, or `None` when none is installed."""
        ...

    async def describe(self, dataset_id: DatasetId) -> DatasetRef: ...

    async def read_series(self, dataset_id: DatasetId) -> DailySeries: ...

    async def write_point(
        self, series: DailySeries, requested_h3: str, request: Mapping[str, str]
    ) -> None:
        """Replace the point store named by `series.dataset.dataset_id` with the full series.

        `requested_h3` is the cell of the point that was asked for; it becomes an alias of
        the dataset, so the next request from that cell is answered locally. `request` is
        what was asked of the source, kept as provenance. A series that breaks a rule of
        `validate_daily` raises `WeatherDataError` and nothing changes.
        """
        ...
