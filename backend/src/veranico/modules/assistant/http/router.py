"""Routes of `assistant`: the chat stream, a stored conversation and the recorded replay.

Stub of the foundation milestone: path, method, operation id, security scheme and schemas
are final. Plan 06 replaces the handler bodies.

The streaming handlers return a response object and are not generators: a failure before
the stream starts (allowance, validation, an unknown conversation) must still be answered
with a problem document, which a generator route cannot do once it has been called.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from veranico.modules.access.contracts import VisitorRef
from veranico.modules.assistant.contracts import AssistantFacade, ChatRequest, ConversationView
from veranico.modules.assistant.http.schemas import EventStreamResponse
from veranico.shared.infrastructure.http_auth import browser_principal, visitor_ref
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.ids import ConversationId, Locale
from veranico.shared.kernel.principal import Principal

Browser = Annotated[Principal, Depends(browser_principal)]
Visitor = Annotated[VisitorRef, Depends(visitor_ref)]

_STREAM: dict[int | str, dict[str, Any]] = {
    200: {"description": "Server-sent events, each one an `AgentEvent` of the contract."}
}


def build_router(facade: AssistantFacade) -> APIRouter:
    router = APIRouter(tags=["assistant"])

    @router.post(
        "/chat",
        operation_id="chat",
        response_class=EventStreamResponse,
        response_model=None,
        responses=_STREAM,
    )
    async def chat(
        principal: Browser, visitor: Visitor, request: ChatRequest
    ) -> EventStreamResponse:
        raise NotImplementedYetError

    @router.get("/conversations/{id}", operation_id="get_conversation")
    async def get_conversation(
        principal: Browser, conversation_id: Annotated[ConversationId, Path(alias="id")]
    ) -> ConversationView:
        raise NotImplementedYetError

    @router.get(
        "/replays/{locale}",
        operation_id="get_replay",
        response_class=EventStreamResponse,
        response_model=None,
        responses=_STREAM,
    )
    async def get_replay(principal: Browser, locale: Locale) -> EventStreamResponse:
        raise NotImplementedYetError

    return router
