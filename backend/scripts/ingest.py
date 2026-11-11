"""Fetch and cache the point history of one location from Open-Meteo (plan 01).

    make ingest LAT=<lat> LON=<lon>
    uv run python scripts/ingest.py --lat=<lat> --lon=<lon>

Builds the `climate` module over the weather store the settings name, calls
`ensure_history` and prints the resulting `DatasetRef` as JSON. A second run for the same
point makes no network call.

Exit codes: 0 cached, 1 failed, 3 no HTTP response was obtained (the network is
unavailable; reported as open by `gate.py`).

The script reads only the `VERANICO_CLIMATE__*` variables, so it runs without the secrets
the application needs to start.
"""

import argparse
import asyncio
import sys

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.climate.module import assemble, weather_store
from veranico.shared.infrastructure.settings import ClimateSettings
from veranico.shared.kernel.clock import SystemClock
from veranico.shared.kernel.errors import DomainError, WeatherSourceUnavailableError

EXIT_OK, EXIT_FAILED, EXIT_OPEN = 0, 1, 3


class IngestSettings(BaseSettings):
    """The climate group of the application settings, read from the same variables."""

    model_config = SettingsConfigDict(
        env_prefix="VERANICO_", env_nested_delimiter="__", env_ignore_empty=True, extra="ignore"
    )

    climate: ClimateSettings = ClimateSettings()


async def ingest(facade: ClimateFacade, lat: float, lon: float) -> int:
    try:
        dataset = await facade.ensure_history(lat, lon)
    except WeatherSourceUnavailableError as error:
        if isinstance(error.__cause__, httpx.TransportError):
            print("ingest: open, no HTTP response from the weather source", file=sys.stderr)
            return EXIT_OPEN
        print(f"ingest: failed, {error.code}", file=sys.stderr)
        return EXIT_FAILED
    except DomainError as error:
        print(f"ingest: failed, {error.code}", file=sys.stderr)
        return EXIT_FAILED
    print(dataset.model_dump_json(indent=2))
    return EXIT_OK


async def run(lat: float, lon: float) -> int:
    settings = IngestSettings().climate
    clock = SystemClock()
    async with httpx.AsyncClient() as http:
        facade = assemble(settings, clock, http, weather_store(settings, clock))
        return await ingest(facade, lat, lon)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and cache the history of one point.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    arguments = parser.parse_args(argv)
    return asyncio.run(run(arguments.lat, arguments.lon))


if __name__ == "__main__":
    sys.exit(main())
