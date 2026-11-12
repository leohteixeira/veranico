"""Wiring of `quoting`. Only `bootstrap.py` imports this file."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

import httpx
from fastapi import APIRouter
from google.cloud import tasks_v2
from google.cloud.firestore import AsyncClient

from veranico.modules.access.contracts import AccessFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.application.facade import QuotingService
from veranico.modules.quoting.contracts import CarrierCatalog, OutboxDispatcher, QuotingFacade
from veranico.modules.quoting.http.router import build_router
from veranico.modules.quoting.infrastructure.cloud_tasks_dispatcher import CloudTasksDispatcher
from veranico.modules.quoting.infrastructure.firestore_idempotency import (
    FirestoreIdempotencyStore,
)
from veranico.modules.quoting.infrastructure.firestore_outbox import FirestoreOutboxStore
from veranico.modules.quoting.infrastructure.firestore_quotes import FirestoreQuoteRepository
from veranico.modules.quoting.infrastructure.relay_dispatcher import RelayDispatcher
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock


@dataclass(frozen=True, kw_only=True)
class QuotingDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient
    pricing: PricingFacade
    climate: ClimateFacade  # quoting resolves the grid cell and the dataset itself
    access: AccessFacade  # unused: the principal arrives from `http_auth`
    carriers: CarrierCatalog
    dispatcher: OutboxDispatcher


@dataclass(frozen=True, kw_only=True)
class QuotingModule:
    facade: QuotingFacade
    routers: Sequence[APIRouter]


def build(deps: QuotingDeps) -> QuotingModule:
    settings, firestore = deps.settings, deps.firestore
    delivery = settings.delivery
    ttl = timedelta(days=settings.access.workspace_ttl_days)
    facade = QuotingService(
        quotes=FirestoreQuoteRepository(firestore, ttl=ttl),
        idempotency=FirestoreIdempotencyStore(firestore, ttl=ttl),
        outbox=FirestoreOutboxStore(firestore),
        climate=deps.climate,
        pricing=deps.pricing,
        carriers=deps.carriers,
        dispatcher=deps.dispatcher,
        clock=deps.clock,
        sweep_age_seconds=delivery.sweep_age_seconds,
        retry_window_seconds=delivery.retry_window_seconds,
    )
    router = build_router(facade, sweep_age_seconds=delivery.sweep_age_seconds)
    return QuotingModule(facade=facade, routers=(router,))


def build_dispatcher(
    settings: Settings, clock: Clock, firestore: AsyncClient, http: httpx.AsyncClient
) -> OutboxDispatcher:
    """Build the dispatcher adapter that the dispatcher kind setting names.

    The relay also exposes async `start()` and `stop()`; the application lifespan calls
    them. Nothing is started here.
    """
    delivery = settings.delivery
    outbox = FirestoreOutboxStore(firestore)
    if delivery.dispatcher == "relay":
        token = delivery.internal_token if delivery.internal_auth == "token" else None
        return RelayDispatcher(
            outbox=outbox,
            http=http,
            clock=clock,
            base_url=delivery.internal_base_url,
            internal_token=token.get_secret_value() if token is not None else None,
            poll_interval_seconds=delivery.relay_poll_interval_seconds,
            backoff_base_seconds=delivery.relay_backoff_base_seconds,
            backoff_cap_seconds=delivery.relay_backoff_cap_seconds,
            # The relay stands in for the queue, so a call gets the queue's deadline.
            call_timeout_seconds=delivery.tasks_dispatch_deadline_seconds,
        )
    if (
        delivery.tasks_project is None
        or delivery.oidc_invoker_email is None
        or delivery.oidc_audience is None
    ):
        raise ValueError(
            "the cloud_tasks dispatcher needs the tasks project, the OIDC invoker email "
            "and the OIDC audience"
        )
    return CloudTasksDispatcher(
        client=tasks_v2.CloudTasksAsyncClient(),
        outbox=outbox,
        project=delivery.tasks_project,
        location=delivery.tasks_location,
        queue=delivery.tasks_queue,
        base_url=delivery.internal_base_url,
        service_account_email=delivery.oidc_invoker_email,
        audience=delivery.oidc_audience,
        dispatch_deadline_seconds=delivery.tasks_dispatch_deadline_seconds,
    )
