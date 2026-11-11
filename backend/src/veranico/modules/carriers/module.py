"""Wiring of `carriers`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 04 replaces the body of `build` and keeps its signature.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.carriers.contracts import CarriersFacade, DeliveryOutcome
from veranico.modules.quoting.contracts import CarrierCatalog, QuotingFacade
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import EventId


@dataclass(frozen=True, kw_only=True)
class CarriersDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient
    http: httpx.AsyncClient
    quoting: QuotingFacade | None  # None on the carrier role, which never calls quoting


@dataclass(frozen=True, kw_only=True)
class CarriersModule:
    facade: CarriersFacade
    routers: Sequence[APIRouter]  # API role
    carrier_router: APIRouter  # carrier role, mounted at the root


class _StubCarriersFacade:
    def catalog(self) -> CarrierCatalog:
        raise NotImplementedError

    async def deliver(self, event_id: EventId, attempt: int) -> DeliveryOutcome:
        raise NotImplementedError


def build(deps: CarriersDeps) -> CarriersModule:
    return CarriersModule(facade=_StubCarriersFacade(), routers=(), carrier_router=APIRouter())
