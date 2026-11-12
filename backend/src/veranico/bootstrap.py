"""Composition root: the only place that builds modules and wires one into another.

Each role builds only what it serves. `APP_ROLE=api` builds the seven modules in dependency
order; `APP_ROLE=carrier` builds `carriers` alone, without a quoting facade.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access import module as access_module
from veranico.modules.assistant import module as assistant_module
from veranico.modules.carriers import module as carriers_module
from veranico.modules.carriers.contracts import CarriersFacade
from veranico.modules.climate import module as climate_module
from veranico.modules.documents import module as documents_module
from veranico.modules.pricing import module as pricing_module
from veranico.modules.quoting import module as quoting_module
from veranico.modules.quoting.contracts import CarrierInfo, OutboxDispatcher
from veranico.shared.infrastructure.blobs import blob_store
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock, SystemClock


@dataclass(frozen=True, kw_only=True)
class Container:
    """What a role built. The modules a role does not serve are `None`."""

    settings: Settings
    clock: Clock
    shutdown: asyncio.Event  # set on SIGTERM; `assistant` ends open streams on it
    firestore: AsyncClient
    http: httpx.AsyncClient
    owns_http: bool  # false when the caller passed the client and closes it itself
    dispatcher: OutboxDispatcher | None
    access: access_module.AccessModule | None
    climate: climate_module.ClimateModule | None
    pricing: pricing_module.PricingModule | None
    quoting: quoting_module.QuotingModule | None
    carriers: carriers_module.CarriersModule
    documents: documents_module.DocumentsModule | None
    assistant: assistant_module.AssistantModule | None

    @property
    def api_routers(self) -> Sequence[APIRouter]:
        """The routers of the API role, in module order."""
        modules = (
            self.access,
            self.climate,
            self.pricing,
            self.quoting,
            self.carriers,
            self.documents,
            self.assistant,
        )
        return [router for module in modules if module is not None for router in module.routers]

    async def close(self) -> None:
        """Close the shared clients."""
        if self.owns_http:
            await self.http.aclose()
        await close_firestore(self.firestore)


class _CarrierCatalogForwarder:
    """The `CarrierCatalog` that `quoting` receives before `carriers` exists.

    `quoting` declares the port and `carriers` implements it, but `carriers` is built after
    `quoting` because it needs the quoting facade. The forwarder asks the carriers facade
    for its catalogue each time it is used. It is the only forwarder in the application.
    """

    def __init__(self) -> None:
        self._carriers: CarriersFacade | None = None

    def bind(self, carriers: CarriersFacade) -> None:
        self._carriers = carriers

    def get(self, carrier_id: str) -> CarrierInfo | None:
        return self._facade().catalog().get(carrier_id)

    def all(self) -> list[CarrierInfo]:
        return self._facade().catalog().all()

    def _facade(self) -> CarriersFacade:
        if self._carriers is None:
            raise RuntimeError("the carrier catalogue was used before the container was built")
        return self._carriers


def build_container(
    settings: Settings,
    *,
    model_client: object | None = None,
    http: httpx.AsyncClient | None = None,
) -> Container:
    """Build the modules of the role the settings name. Opens no connection.

    `model_client` becomes `AssistantDeps.model_client`; `None` lets `assistant` build the
    client its selector setting names. `http` is shared by every module that makes HTTP
    calls; with a transport that replays recorded responses it runs `climate` offline.
    These two are the only injection points.
    """
    clock = SystemClock()
    shutdown = asyncio.Event()
    firestore = firestore_client(settings)
    shared_http = http if http is not None else httpx.AsyncClient()

    if settings.app_role == "carrier":
        return Container(
            settings=settings,
            clock=clock,
            shutdown=shutdown,
            firestore=firestore,
            http=shared_http,
            owns_http=http is None,
            dispatcher=None,
            access=None,
            climate=None,
            pricing=None,
            quoting=None,
            carriers=carriers_module.build(
                carriers_module.CarriersDeps(
                    settings=settings,
                    clock=clock,
                    firestore=firestore,
                    http=shared_http,
                    quoting=None,
                )
            ),
            documents=None,
            assistant=None,
        )

    blobs = blob_store(settings)
    access = access_module.build(
        access_module.AccessDeps(settings=settings, clock=clock, firestore=firestore)
    )
    climate = climate_module.build(
        climate_module.ClimateDeps(settings=settings, clock=clock, http=shared_http, blobs=blobs)
    )
    pricing = pricing_module.build(
        pricing_module.PricingDeps(settings=settings, climate=climate.facade)
    )
    dispatcher = quoting_module.build_dispatcher(
        settings=settings, clock=clock, firestore=firestore, http=shared_http
    )
    catalog = _CarrierCatalogForwarder()
    quoting = quoting_module.build(
        quoting_module.QuotingDeps(
            settings=settings,
            clock=clock,
            firestore=firestore,
            pricing=pricing.facade,
            climate=climate.facade,
            access=access.facade,
            carriers=catalog,
            dispatcher=dispatcher,
        )
    )
    carriers = carriers_module.build(
        carriers_module.CarriersDeps(
            settings=settings,
            clock=clock,
            firestore=firestore,
            http=shared_http,
            quoting=quoting.facade,
        )
    )
    catalog.bind(carriers.facade)
    documents = documents_module.build(
        documents_module.DocumentsDeps(
            settings=settings,
            clock=clock,
            blobs=blobs,
            quoting=quoting.facade,
            climate=climate.facade,
            access=access.facade,
        )
    )
    assistant = assistant_module.build(
        assistant_module.AssistantDeps(
            settings=settings,
            clock=clock,
            firestore=firestore,
            access=access.facade,
            climate=climate.facade,
            pricing=pricing.facade,
            quoting=quoting.facade,
            carriers=carriers.facade,
            documents=documents.facade,
            model_client=model_client,
            shutdown=shutdown,
        )
    )
    return Container(
        settings=settings,
        clock=clock,
        shutdown=shutdown,
        firestore=firestore,
        http=shared_http,
        owns_http=http is None,
        dispatcher=dispatcher,
        access=access,
        climate=climate,
        pricing=pricing,
        quoting=quoting,
        carriers=carriers,
        documents=documents,
        assistant=assistant,
    )
