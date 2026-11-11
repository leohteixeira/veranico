"""Wiring of `assistant`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 06 replaces the body of `build` and keeps its signature.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access.contracts import AccessFacade, VisitorRef
from veranico.modules.assistant.contracts import (
    AgentEvent,
    AssistantFacade,
    ChatRequest,
    ConversationView,
)
from veranico.modules.assistant.http.router import build_router
from veranico.modules.carriers.contracts import CarriersFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import ConversationId, Locale
from veranico.shared.kernel.principal import Principal


@dataclass(frozen=True, kw_only=True)
class AssistantDeps:
    settings: Settings
    clock: Clock
    firestore: AsyncClient
    access: AccessFacade
    climate: ClimateFacade
    pricing: PricingFacade
    quoting: QuotingFacade
    carriers: CarriersFacade
    documents: DocumentsFacade
    # Plan 06 narrows the type to its `ModelClient` port. `None` means the module builds
    # the client its selector setting names.
    model_client: object | None = None
    shutdown: asyncio.Event  # set on SIGTERM; open streams end with the `shutting_down` code


@dataclass(frozen=True, kw_only=True)
class AssistantModule:
    facade: AssistantFacade
    routers: Sequence[APIRouter]


class _StubAssistantFacade:
    def chat(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError

    async def conversation(
        self, principal: Principal, conversation_id: ConversationId
    ) -> ConversationView:
        raise NotImplementedError

    def replay(self, locale: Locale) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError


def build(deps: AssistantDeps) -> AssistantModule:
    facade = _StubAssistantFacade()
    return AssistantModule(facade=facade, routers=(build_router(facade),))
