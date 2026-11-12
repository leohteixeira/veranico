"""Wiring of `carriers`. Only `bootstrap.py` imports this file."""

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.carriers.application.deliver import DeliveryService
from veranico.modules.carriers.application.delivery_call import DeliveryCalls
from veranico.modules.carriers.application.receive import Receiver
from veranico.modules.carriers.contracts import CarriersFacade, DeliveryOutcome
from veranico.modules.carriers.domain.directory import CarrierDirectory
from veranico.modules.carriers.http.carrier_router import build_carrier_router
from veranico.modules.carriers.http.router import build_router
from veranico.modules.carriers.infrastructure.receipts import FirestoreReceiptStore
from veranico.modules.carriers.infrastructure.webhook_sender import HttpxWebhookSender
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


class _CarrierRoleFacade:
    """The facade of the carrier role: the mock carrier receives webhooks and delivers none."""

    def __init__(self, directory: CarrierDirectory) -> None:
        self._directory = directory

    def catalog(self) -> CarrierCatalog:
        return self._directory

    async def deliver(self, event_id: EventId, attempt: int) -> DeliveryOutcome:
        raise RuntimeError("the carrier role does not deliver webhooks")


def build(deps: CarriersDeps) -> CarriersModule:
    delivery = deps.settings.delivery
    if delivery.webhook_signing_secret is None:
        # Settings validation already requires it on both roles; this narrows the type.
        raise RuntimeError("the webhook signing secret is not configured")
    signing_secret = delivery.webhook_signing_secret.get_secret_value()
    directory = CarrierDirectory(delivery.carrier_base_url)
    # Built on both roles because `CarriersModule` carries it; only the carrier role mounts
    # it, so the API role never reads or writes the receipts collection.
    carrier_router = build_carrier_router(
        Receiver(
            store=FirestoreReceiptStore(deps.firestore),
            clock=deps.clock,
            signing_secret=signing_secret,
            tolerance_seconds=delivery.timestamp_tolerance_seconds,
            fail_first_attempt=delivery.carrier_fail_first_attempt,
        )
    )
    if deps.quoting is None:
        # Carrier role: only the mock carrier's router; the delivery use case is not built.
        return CarriersModule(
            facade=_CarrierRoleFacade(directory), routers=(), carrier_router=carrier_router
        )
    service = DeliveryService(
        quoting=deps.quoting,
        directory=directory,
        sender=HttpxWebhookSender(
            deps.http,
            connect_timeout_seconds=delivery.webhook_connect_timeout_seconds,
            total_timeout_seconds=delivery.webhook_total_timeout_seconds,
        ),
        clock=deps.clock,
        signing_secret=signing_secret,
    )
    calls = DeliveryCalls(
        carriers=service, quoting=deps.quoting, attempt_limit=delivery.attempt_limit
    )
    return CarriersModule(
        facade=service, routers=(build_router(calls),), carrier_router=carrier_router
    )
