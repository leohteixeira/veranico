"""Wiring of `assistant`. Only `bootstrap.py` imports this file."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from fastapi import APIRouter
from google.cloud.firestore import AsyncClient

from veranico.modules.access.contracts import AccessFacade, VisitorRef
from veranico.modules.assistant.application.chat_service import ChatService
from veranico.modules.assistant.application.ports import (
    ModelClient,
    ModelEvent,
    ModelRequest,
    ModelUnavailable,
)
from veranico.modules.assistant.application.prompt import load_system_prompt
from veranico.modules.assistant.application.replay import Replays
from veranico.modules.assistant.application.tools.registry import ToolRegistry
from veranico.modules.assistant.application.turn import TurnDeps
from veranico.modules.assistant.contracts import (
    AgentEvent,
    AssistantFacade,
    ChatRequest,
    ConversationView,
)
from veranico.modules.assistant.http.router import build_router
from veranico.modules.assistant.infrastructure.firestore_conversations import (
    FirestoreConversationStore,
)
from veranico.modules.assistant.infrastructure.scripted_model import ScriptedModelClient
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
    # A `ModelClient` (tests, the evaluation harness). `None` means the module builds the
    # client its selector setting names. Typed as `object` because the composition root
    # passes it through without knowing this module's port.
    model_client: object | None = None
    shutdown: asyncio.Event  # set on SIGTERM; open streams end with the `shutting_down` code


@dataclass(frozen=True, kw_only=True)
class AssistantModule:
    facade: AssistantFacade
    routers: Sequence[APIRouter]


class _Facade:
    def __init__(self, service: ChatService, replays: Replays) -> None:
        self._service = service
        self._replays = replays

    def chat(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> AsyncIterator[AgentEvent]:
        return self._service.chat(principal, visitor, request)

    async def conversation(
        self, principal: Principal, conversation_id: ConversationId
    ) -> ConversationView:
        return await self._service.conversation(principal, conversation_id)

    def replay(self, locale: Locale) -> AsyncIterator[AgentEvent]:
        return self._replays.stream(locale)


class _NoModelYet:
    """Stands in for the Anthropic adapter until it exists: every call fails, nothing is spent."""

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        raise ModelUnavailable("the Anthropic model client is not built yet")
        yield  # pragma: no cover - makes this function an async generator


def _model_client(deps: AssistantDeps) -> ModelClient:
    if deps.model_client is not None:
        return cast("ModelClient", deps.model_client)
    if deps.settings.assistant.model_client == "scripted":
        return ScriptedModelClient.happy_path()
    return _NoModelYet()


def build(deps: AssistantDeps) -> AssistantModule:
    settings = deps.settings
    service = ChatService(
        TurnDeps(
            settings=settings,
            access=deps.access,
            store=FirestoreConversationStore(
                deps.firestore,
                deps.clock,
                ttl=timedelta(days=settings.access.workspace_ttl_days),
            ),
            model=_model_client(deps),
            registry=ToolRegistry(
                climate=deps.climate,
                pricing=deps.pricing,
                quoting=deps.quoting,
                documents=deps.documents,
                carriers=deps.carriers,
            ),
            prompt=load_system_prompt(),
            shutdown=deps.shutdown,
        )
    )
    facade = _Facade(service, Replays())
    return AssistantModule(facade=facade, routers=(build_router(facade),))
