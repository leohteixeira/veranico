"""Wiring of `climate`. Only `bootstrap.py` imports this file (and the data scripts).

`build(deps)` keeps the signature of the foundation milestone. `assemble` is the same
wiring from the parts the module really needs, and `store_from_environment` builds the
weather store alone: the data scripts (`scripts/ingest.py`, `scripts/build_cube.py`) must
run without the secrets the full `Settings` require.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter
from google.cloud.storage import Client as StorageClient
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from veranico.modules.climate.application.ensure_history import EnsureHistory
from veranico.modules.climate.application.export_evidence import ExportEvidence
from veranico.modules.climate.application.facade import Climate
from veranico.modules.climate.application.ports import WeatherStore
from veranico.modules.climate.application.resolve_location import ResolveLocation
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.climate.http.router import build_router
from veranico.modules.climate.infrastructure.gcs_store import GcsWeatherStore
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.netcdf import encode_evidence
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive
from veranico.modules.climate.infrastructure.open_meteo_geocoding import OpenMeteoGeocoder
from veranico.shared.infrastructure.blobs import BlobStore, GcsBlobStore
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


@dataclass(frozen=True, kw_only=True)
class GcsTarget:
    """What the Cloud Storage weather store needs beyond the climate settings."""

    blobs: BlobStore  # over the same bucket
    bucket: str
    emulator_host: str | None  # with the scheme; `None` for the real service


class StoreSettings(BaseSettings):
    """What the weather store needs, read from the same variables as `Settings`."""

    model_config = SettingsConfigDict(
        env_prefix="VERANICO_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
        validate_by_name=True,
        validate_by_alias=True,
    )

    climate: ClimateSettings = ClimateSettings()
    firestore_project: str = "veranico-dev"  # the Google Cloud project of the service
    storage_bucket: str = "veranico-dev"
    storage_emulator_host: str | None = Field(default=None, alias="STORAGE_EMULATOR_HOST")


def build(deps: ClimateDeps) -> ClimateModule:
    settings = deps.settings
    target = None
    if settings.climate.store_backend == "gcs":
        if settings.blob_backend != "gcs":
            raise ValueError(
                "VERANICO_CLIMATE__STORE_BACKEND=gcs needs VERANICO_BLOB_BACKEND=gcs: "
                "the manifests of the weather store are objects of the same bucket"
            )
        target = GcsTarget(
            blobs=deps.blobs,
            bucket=settings.storage_bucket,
            emulator_host=settings.storage_emulator_host,
        )
    store = weather_store(settings.climate, deps.clock, target)
    facade = assemble(settings.climate, deps.clock, deps.http, store)
    return ClimateModule(facade=facade, routers=(build_router(facade),))


def weather_store(
    settings: ClimateSettings, clock: Clock, gcs: GcsTarget | None = None
) -> WeatherStore:
    """The store adapter the settings name."""
    if settings.store_backend == "local":
        return LocalWeatherStore(settings.store_root, clock)
    if gcs is None:
        raise ValueError("the Cloud Storage weather store needs its bucket")
    return GcsWeatherStore(gcs.blobs, gcs.bucket, gcs.emulator_host, clock)


def store_from_environment(settings: StoreSettings, clock: Clock) -> WeatherStore:
    """The weather store for a data script, built from the environment alone."""
    if settings.climate.store_backend == "local":
        return weather_store(settings.climate, clock)
    if settings.storage_emulator_host is not None:
        client = StorageClient(
            project=settings.firestore_project,
            client_options={"api_endpoint": settings.storage_emulator_host},
            use_auth_w_custom_endpoint=False,  # anonymous credentials
        )
    else:
        client = StorageClient(project=settings.firestore_project)
    target = GcsTarget(
        blobs=GcsBlobStore(client, settings.storage_bucket),
        bucket=settings.storage_bucket,
        emulator_host=settings.storage_emulator_host,
    )
    return weather_store(settings.climate, clock, target)


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
        cube_cache_size=settings.cube_cache_size,
    )
