"""Wiring of `climate`. Only `bootstrap.py` imports this file (and the data scripts).

`build(deps)` keeps the signature of the foundation milestone. `assemble` is the same
wiring from the parts the module really needs, for `scripts/ingest.py`, which must run
without the secrets the full `Settings` require.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter

from veranico.modules.climate.application.ensure_history import EnsureHistory
from veranico.modules.climate.application.export_evidence import ExportEvidence
from veranico.modules.climate.application.facade import Climate
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.application.resolve_location import ResolveLocation
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.climate.http.router import build_router
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.netcdf import encode_evidence
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive
from veranico.modules.climate.infrastructure.open_meteo_geocoding import OpenMeteoGeocoder
from veranico.shared.infrastructure.blobs import BlobStore
from veranico.shared.infrastructure.settings import ClimateSettings, Settings
from veranico.shared.kernel.clock import Clock


@dataclass(frozen=True, kw_only=True)
class ClimateDeps:
    settings: Settings
    clock: Clock
    http: httpx.AsyncClient  # with a replaying transport, the offline seam of the module
    blobs: BlobStore


@dataclass(frozen=True, kw_only=True)
class ClimateModule:
    facade: ClimateFacade
    routers: Sequence[APIRouter]


def build(deps: ClimateDeps) -> ClimateModule:
    climate = deps.settings.climate
    facade = assemble(climate, deps.clock, deps.http, weather_store(climate, deps.clock))
    return ClimateModule(facade=facade, routers=(build_router(facade),))


def weather_store(settings: ClimateSettings, clock: Clock) -> WeatherStore:
    """The store adapter the settings name."""
    if settings.store_backend == "local":
        return LocalWeatherStore(settings.store_root, clock)
    raise NotImplementedError("the Cloud Storage weather store arrives with plan task 11")


def assemble(
    settings: ClimateSettings, clock: Clock, http: httpx.AsyncClient, store: WeatherStore
) -> ClimateFacade:
    # Retry jitter exists to spread instances that failed together, so each process seeds
    # its generator from the operating system. Tests inject seeded generators instead.
    rng = random.Random()
    archive = OpenMeteoArchive(http, settings, rng=rng)
    geocoder = OpenMeteoGeocoder(http, settings, rng=rng)
    return Climate(
        store=store,
        resolve=ResolveLocation(geocoder),
        ensure=EnsureHistory(store, archive, clock, first_year=settings.first_year),
        export=ExportEvidence(store, encode_evidence),
    )
