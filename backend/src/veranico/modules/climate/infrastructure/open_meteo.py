"""`PointSource` on the Open-Meteo Historical Weather API (`/v1/archive`).

Checked against https://open-meteo.com/en/docs/historical-weather-api and against live
answers on 2026-11-11:

* `daily=precipitation_sum` is the daily precipitation sum in millimetres. Daily variables
  need `timezone`; `auto` resolves the zone from the coordinates, so a day is a local day.
* The answer's `latitude` and `longitude` are the centre of the grid cell that was used,
  which may lie a few kilometres from the requested point. That grid point keys the store.
* A missing value is JSON `null`. An invalid request is HTTP 400 with `{"error": true}`.
* `models` selects the reanalysis; the page does not list its values. See `ARCHIVE_MODEL`
  for what was measured.
* A cold request for all 76 years took 14 to 22 seconds, one for 10 years under 2 seconds.
  With a per-attempt timeout of 10 seconds the range is therefore asked in blocks of
  `YEARS_PER_REQUEST` years.
"""

import asyncio
import random
from collections.abc import Mapping
from typing import Any, Final

import httpx
import numpy as np

from veranico.modules.climate.application.ports import PointFetch
from veranico.modules.climate.contracts import GridPoint
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.infrastructure.http_retry import RetryingGet, Sleep
from veranico.shared.infrastructure.settings import ClimateSettings

ARCHIVE_PATH = "/v1/archive"
DAILY_VARIABLE = "precipitation_sum"
# ADR 0017. Measured on 2026-11-11 at -15.03, -47.93: `era5_land` answers on the 0.1 degree
# grid but every precipitation value is null (Open-Meteo does not serve ERA5-Land
# precipitation; `fixtures/open_meteo/era5_land_nulls_2020_01.json` is that answer).
# `era5_seamless` reports the 0.1 degree grid point with the values of ERA5, which would make
# neighbouring 0.1 degree points look like different cells with one history. `era5` answers
# with the same values at its own 0.25 degree grid point, so that is what is asked, and the
# stored source is `era5/open-meteo`.
ARCHIVE_MODEL = "era5"
SOURCE: Final = "era5/open-meteo"
TIMEZONE = "auto"
YEARS_PER_REQUEST = 10


class SourceRejectedError(Exception):
    """The source refused the request (a 4xx other than 429). Not retried, not client-facing."""


class OpenMeteoArchive:
    def __init__(
        self,
        http: httpx.AsyncClient,
        settings: ClimateSettings,
        *,
        rng: random.Random,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._url = settings.archive_base_url.rstrip("/") + ARCHIVE_PATH
        self._get = RetryingGet(
            http,
            attempts=settings.attempts,
            backoff_base_seconds=settings.backoff_base_seconds,
            timeout_seconds=settings.attempt_timeout_seconds,
            rng=rng,
            sleep=sleep,
        )

    async def fetch(self, lat: float, lon: float, first_year: int, last_year: int) -> PointFetch:
        fixed = {
            "latitude": str(lat),
            "longitude": str(lon),
            "daily": DAILY_VARIABLE,
            "models": ARCHIVE_MODEL,
            "timezone": TIMEZONE,
        }
        grid_point: GridPoint | None = None
        dates: list[np.ndarray] = []
        values: list[np.ndarray] = []
        attempts = 0
        for start in range(first_year, last_year + 1, YEARS_PER_REQUEST):
            end = min(start + YEARS_PER_REQUEST - 1, last_year)
            answer = await self._get.get(
                self._url, {**fixed, "start_date": f"{start}-01-01", "end_date": f"{end}-12-31"}
            )
            attempts += answer.attempts
            block_point, block_dates, block_values = _parse(answer.response)
            if grid_point is not None and block_point != grid_point:
                raise WeatherDataError("the source answered one point from two grid cells")
            grid_point = block_point
            dates.append(block_dates)
            values.append(block_values)
        if grid_point is None:
            raise ValueError(f"empty range of years: {first_year} to {last_year}")
        return PointFetch(
            grid_point=grid_point,
            dates=np.concatenate(dates),
            precipitation_mm=np.concatenate(values),
            source=SOURCE,
            request={**fixed, "url": self._url},
            attempts=attempts,
        )


def _parse(response: httpx.Response) -> tuple[GridPoint, np.ndarray, np.ndarray]:
    if response.status_code != 200:
        raise SourceRejectedError(f"the weather source answered HTTP {response.status_code}")
    try:
        body: Mapping[str, Any] = response.json()
        unit = body["daily_units"][DAILY_VARIABLE]
        grid_point = GridPoint(lat=float(body["latitude"]), lon=float(body["longitude"]))
        dates = np.array(body["daily"]["time"], dtype="datetime64[D]")
        # JSON null becomes None, which float64 stores as NaN.
        values = np.array(body["daily"][DAILY_VARIABLE], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherDataError("unexpected answer shape from the weather source") from error
    if unit != "mm":
        raise WeatherDataError(f"precipitation unit is {unit!r}, expected 'mm'")
    if dates.shape != values.shape:
        raise WeatherDataError("dates and values of the weather source differ in length")
    return grid_point, dates, values
