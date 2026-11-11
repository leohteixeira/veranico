"""Use case behind `ClimateFacade.ensure_history`: make a point's history available.

Order of resolution (SPEC 4.2, 4.4): what the store already knows for the point (a cell of
an installed cube, or the dataset the clicked H3 cell resolved to earlier), and only then
the point source. A stored point dataset is topped up when it ends before the last complete
year: only the missing years are fetched.

Two concurrent calls for one point both fetch and both write the same data; the store's
atomic switch leaves one valid store, so there is no lock here.
"""

from datetime import date

import numpy as np

from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.ports import PointFetch, PointSource, WeatherStore
from veranico.modules.climate.contracts import DailySeries, DatasetRef
from veranico.modules.climate.domain.coverage import last_complete_year, missing_years
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.validation import validate_daily
from veranico.shared.infrastructure.telemetry import (
    ATTR_CLIMATE_ATTEMPTS,
    ATTR_CLIMATE_DATASET_ID,
    ATTR_CLIMATE_YEARS_FETCHED,
    SPAN_CLIMATE_INGEST,
    tracer,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import OutsideCoverageError
from veranico.shared.kernel.ids import point_dataset_id


class EnsureHistory:
    def __init__(
        self, store: WeatherStore, source: PointSource, clock: Clock, first_year: int
    ) -> None:
        self._store = store
        self._source = source
        self._clock = clock
        self._first_year = first_year
        self._tracer = tracer()

    async def __call__(self, lat: float, lon: float) -> DatasetRef:
        last_year = last_complete_year(self._clock.now().date())
        dataset_id = await self._store.locate(lat, lon)
        if dataset_id is None:
            return await self._ingest(lat, lon, None, [(self._first_year, last_year)])
        stored = await self._store.describe(dataset_id)
        if stored.kind == "cube":
            return stored
        missing = missing_years(stored.first_year, stored.last_year, self._first_year, last_year)
        if not missing:
            return stored
        return await self._ingest(lat, lon, stored, _runs(missing))

    async def _ingest(
        self, lat: float, lon: float, stored: DatasetRef | None, runs: list[tuple[int, int]]
    ) -> DatasetRef:
        """Fetch the runs of years, merge them with what is stored, validate and write."""
        with self._tracer.start_as_current_span(SPAN_CLIMATE_INGEST) as span:
            # A top-up asks for the stored grid point itself, so the source answers from
            # the same grid cell as before.
            ask = (lat, lon) if stored is None else (stored.grid_point.lat, stored.grid_point.lon)
            fetches = [await self._fetch(*ask, first, last) for first, last in runs]
            newest = fetches[-1]
            grid_point = newest.grid_point
            dataset_id = point_dataset_id(h3_cell_of(grid_point.lat, grid_point.lon))
            span.set_attribute(ATTR_CLIMATE_DATASET_ID, dataset_id)
            span.set_attribute(
                ATTR_CLIMATE_YEARS_FETCHED, sum(last - first + 1 for first, last in runs)
            )
            span.set_attribute(ATTR_CLIMATE_ATTEMPTS, sum(fetch.attempts for fetch in fetches))

            parts = [(fetch.dates, fetch.precipitation_mm) for fetch in fetches]
            if stored is not None:
                if any(fetch.grid_point != stored.grid_point for fetch in fetches):
                    raise WeatherDataError("a top-up came from another grid cell than the store")
                series = await self._store.read_series(stored.dataset_id)
                parts.append((series.dates, series.precipitation_mm))
            parts.sort(key=lambda part: part[0][0])
            dates = np.concatenate([part[0] for part in parts])
            precipitation = np.concatenate([part[1] for part in parts])
            if np.isnan(precipitation).all():
                raise OutsideCoverageError("the weather source has no data for this point")
            missing_days = validate_daily(dates, precipitation)

            merged = DailySeries(
                dataset=DatasetRef(
                    dataset_id=dataset_id,
                    kind="point",
                    region_id=None,
                    grid_point=grid_point,
                    first_year=_year(dates[0]),
                    last_year=_year(dates[-1]),
                    days=len(dates),
                    missing_days=missing_days,
                    source=newest.source,
                ),
                dates=dates,
                precipitation_mm=precipitation,
            )
            await self._store.write_point(merged, h3_cell_of(lat, lon), dict(newest.request))
            return await self._store.describe(dataset_id)

    async def _fetch(self, lat: float, lon: float, first_year: int, last_year: int) -> PointFetch:
        fetched = await self._source.fetch(lat, lon, first_year, last_year)
        # Whole years are what coverage is computed from: a short answer must not pass.
        if (
            len(fetched.dates) == 0
            or fetched.dates[0] != np.datetime64(date(first_year, 1, 1))
            or fetched.dates[-1] != np.datetime64(date(last_year, 12, 31))
        ):
            raise WeatherDataError(
                f"the source did not answer the whole years {first_year} to {last_year}"
            )
        return fetched


def _runs(years: list[int]) -> list[tuple[int, int]]:
    """Ascending years as (first, last) runs of consecutive years."""
    runs: list[tuple[int, int]] = []
    for year in years:
        if runs and runs[-1][1] == year - 1:
            runs[-1] = (runs[-1][0], year)
        else:
            runs.append((year, year))
    return runs


def _year(day: np.datetime64) -> int:
    value: date = day.astype("datetime64[D]").item()
    return value.year
