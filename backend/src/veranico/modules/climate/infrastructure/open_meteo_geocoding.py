"""`Geocoder` on the Open-Meteo Geocoding API (`/v1/search`, no key).

Checked against https://open-meteo.com/en/docs/geocoding-api and live answers on 2026-11-11:

* `name` is required; `count` (default 10, at most 100), `language` and `countryCode`
  (ISO 3166-1 alpha-2, filters the results) are optional.
* A result carries `name`, `latitude`, `longitude`, `country_code`, `feature_code` (a GeoNames
  feature code) and `admin1` (the state), among others. Empty fields are left out.
* When nothing matches, the answer has no `results` key at all (seen live; the page does
  not say). An invalid parameter is HTTP 400 with `{"error": true}`.

Only populated places are kept (GeoNames feature codes starting with `PPL`): a search for a
town also returns its airport and similar features, which would make a unique town
ambiguous.
"""

import asyncio
import random
from collections.abc import Mapping
from typing import Any

import httpx

from veranico.modules.climate.application.ports import GeocodeHit
from veranico.modules.climate.domain.brazil import COUNTRY_CODE
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.infrastructure.http_retry import RetryingGet, Sleep
from veranico.modules.climate.infrastructure.open_meteo import SourceRejectedError
from veranico.shared.infrastructure.settings import ClimateSettings

SEARCH_PATH = "/v1/search"
RESULT_COUNT = "10"
LANGUAGE = "pt"
_POPULATED_PLACE = "PPL"


class OpenMeteoGeocoder:
    def __init__(
        self,
        http: httpx.AsyncClient,
        settings: ClimateSettings,
        *,
        rng: random.Random,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._url = settings.geocoding_base_url.rstrip("/") + SEARCH_PATH
        self._get = RetryingGet(
            http,
            attempts=settings.attempts,
            backoff_base_seconds=settings.backoff_base_seconds,
            timeout_seconds=settings.attempt_timeout_seconds,
            rng=rng,
            sleep=sleep,
        )

    async def search(self, name: str) -> list[GeocodeHit]:
        answer = await self._get.get(
            self._url,
            {
                "name": name,
                "count": RESULT_COUNT,
                "language": LANGUAGE,
                "format": "json",
                "countryCode": COUNTRY_CODE,
            },
        )
        response = answer.response
        if response.status_code != 200:
            raise SourceRejectedError(f"the geocoder answered HTTP {response.status_code}")
        try:
            body: Mapping[str, Any] = response.json()
            return [
                GeocodeHit(
                    name=str(result["name"]),
                    lat=float(result["latitude"]),
                    lon=float(result["longitude"]),
                    admin1=result.get("admin1") or None,
                    country_code=str(result["country_code"]),
                )
                for result in body.get("results", [])
                if str(result.get("feature_code", "")).startswith(_POPULATED_PLACE)
            ]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise WeatherDataError("unexpected answer shape from the geocoder") from error
