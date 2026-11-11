"""Wiring of `quoting`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 03 replaces the bodies of `build` and
`build_dispatcher` and keeps their signatures.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access.contracts import AccessFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.contracts import (
    Actor,
    ApprovalView,
    CarrierCatalog,
    CreateQuote,
    Decision,
    DeliveryAttempt,
    OutboxDispatcher,
    QuoteSummary,
    QuoteView,
    QuotingFacade,
    Submission,
    SubmissionApproved,
)
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId
from veranico.shared.kernel.principal import Principal


@dataclass(frozen=True, kw_only=True)
class QuotingDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient
    pricing: PricingFacade
    climate: ClimateFacade  # quoting resolves the grid cell and the dataset itself
    access: AccessFacade
    carriers: CarrierCatalog
    dispatcher: OutboxDispatcher


@dataclass(frozen=True, kw_only=True)
class QuotingModule:
    facade: QuotingFacade
    routers: Sequence[APIRouter]


class _StubQuotingFacade:
    async def create_quote(
        self,
        principal: Principal,
        command: CreateQuote,
        idempotency_key: str | None,
        actor: Actor,
    ) -> QuoteView:
        raise NotImplementedError

    async def get_quote(self, principal: Principal, quote_id: QuoteId) -> QuoteView:
        raise NotImplementedError

    async def list_quotes(self, principal: Principal) -> list[QuoteSummary]:
        raise NotImplementedError

    async def request_submission(
        self, principal: Principal, quote_id: QuoteId, carrier_id: str, actor: Actor
    ) -> Submission:
        raise NotImplementedError

    async def list_approvals(
        self, principal: Principal, status: Literal["pending", "approved", "rejected"] | None
    ) -> list[ApprovalView]:
        raise NotImplementedError

    async def decide(
        self, principal: Principal, approval_id: SubmissionId, decision: Decision
    ) -> ApprovalView:
        raise NotImplementedError

    async def redeliver(self, principal: Principal, approval_id: SubmissionId) -> ApprovalView:
        raise NotImplementedError

    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None:
        raise NotImplementedError

    async def load_event(self, event_id: EventId) -> SubmissionApproved:
        raise NotImplementedError

    async def record_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        raise NotImplementedError

    async def record_delivery_abandoned(self, event_id: EventId) -> None:
        raise NotImplementedError

    async def sweep_outbox(self, older_than_seconds: int) -> int:
        raise NotImplementedError


class _StubDispatcher:
    async def enqueue(self, event_id: EventId) -> None:
        raise NotImplementedError


def build(deps: QuotingDeps) -> QuotingModule:
    return QuotingModule(facade=_StubQuotingFacade(), routers=())


def build_dispatcher(
    settings: Settings, clock: Clock, firestore: AsyncClient, http: httpx.AsyncClient
) -> OutboxDispatcher:
    """Build the dispatcher adapter that the dispatcher kind setting names.

    The returned object may also expose async `start()` and `stop()`; the application
    lifespan calls them when present. Both adapters live in `quoting/infrastructure`.
    """
    return _StubDispatcher()
