"""Wiring of `climate`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 01 replaces the body of `build` and keeps its signature.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter

from veranico.modules.climate.contracts import (
    ClimateFacade,
    DailySeries,
    DatasetRef,
    EvidenceRequest,
    Location,
    LocationCandidates,
    Region,
    RegionCube,
)
from veranico.shared.infrastructure.blobs import BlobStore
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import DatasetId


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


class _StubClimateFacade:
    async def resolve_location(
        self, query: str | None, lat: float | None, lon: float | None
    ) -> Location | LocationCandidates:
        raise NotImplementedError

    async def ensure_history(self, lat: float, lon: float) -> DatasetRef:
        raise NotImplementedError

    async def describe(self, dataset_id: DatasetId) -> DatasetRef:
        raise NotImplementedError

    async def daily_series(self, dataset_id: DatasetId) -> DailySeries:
        raise NotImplementedError

    async def regions(self) -> list[Region]:
        raise NotImplementedError

    async def region_cube(self, region_id: str) -> RegionCube:
        raise NotImplementedError

    async def export_evidence(self, request: EvidenceRequest) -> bytes:
        raise NotImplementedError


def build(deps: ClimateDeps) -> ClimateModule:
    return ClimateModule(facade=_StubClimateFacade(), routers=())
