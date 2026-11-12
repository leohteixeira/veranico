"""Routes of `assistant`: the chat stream, a stored conversation and the recorded replay.

The streaming handlers return a response object and are not generators: a failure before
the stream starts (allowance, validation, an unknown conversation) must still be answered
with a problem document, which a generator route cannot do once it has been called. So
`chat` asks for the first event before it builds the response: everything that can refuse
a message is raised by then, and the first event is always `started`.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from veranico.modules.access.contracts import VisitorRef
from veranico.modules.assistant.contracts import (
    AgentEvent,
    AssistantFacade,
    ChatRequest,
    ConversationView,
)
from veranico.modules.assistant.http.schemas import EventStreamResponse
from veranico.modules.assistant.http.sse import encode
from veranico.shared.infrastructure.http_auth import browser_principal, visitor_ref
from veranico.shared.kernel.ids import ConversationId, Locale
from veranico.shared.kernel.principal import Principal

Browser = Annotated[Principal, Depends(browser_principal)]
Visitor = Annotated[VisitorRef, Depends(visitor_ref)]

_STREAM: dict[int | str, dict[str, Any]] = {
    200: {"description": "Server-sent events, each one an `AgentEvent` of the contract."}
}

# Events must reach the browser as they are produced: no cache, no proxy buffering.
_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _encoded(
    events: AsyncIterator[AgentEvent], first: AgentEvent | None = None
) -> AsyncGenerator[bytes]:
    """The events as bytes. Closing this stream closes `events`, which ends an open turn."""
    async with aclosing(events):  # type: ignore[type-var]  # the facades return async generators; the contract names them by the narrower `AsyncIterator`
        if first is not None:
            yield encode(first)
        async for event in events:
            yield encode(event)


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
        events = facade.chat(principal, visitor, request)
        first = await anext(events)  # a refused message raises here, before any byte is sent
        return EventStreamResponse(_encoded(events, first), headers=_STREAM_HEADERS)

    @router.get("/conversations/{id}", operation_id="get_conversation")
    async def get_conversation(
        principal: Browser, conversation_id: Annotated[ConversationId, Path(alias="id")]
    ) -> ConversationView:
        return await facade.conversation(principal, conversation_id)

    @router.get(
        "/replays/{locale}",
        operation_id="get_replay",
        response_class=EventStreamResponse,
        response_model=None,
        responses=_STREAM,
    )
    async def get_replay(principal: Browser, locale: Locale) -> EventStreamResponse:
        return EventStreamResponse(_encoded(facade.replay(locale)), headers=_STREAM_HEADERS)

    return router
