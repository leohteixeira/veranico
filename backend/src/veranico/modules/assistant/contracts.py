"""Public surface of `assistant`: chat facade, server-sent event models, stored conversations."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from veranico.modules.access.contracts import VisitorRef
from veranico.modules.climate.contracts import GridPoint
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import ConversationId, Locale, QuoteId, SubmissionId
from veranico.shared.kernel.principal import Principal


class ChatRequest(BaseModel, frozen=True):
    conversation_id: ConversationId | None
    message: str  # at most MAX_MESSAGE_CHARS
    locale: Locale
    map_point: GridPoint | None = None  # set when the visitor clicked the map


class ToolError(BaseModel, frozen=True):
    error_code: str
    message: str
    retryable: bool


# Server-sent events. Wire format: "event: <name>\ndata: <json>\n\n"
class Started(
    BaseModel, frozen=True
):  # event: started; always first, so a cut stream still knows its conversation
    conversation_id: ConversationId
    message_id: str


class UserMessage(
    BaseModel, frozen=True
):  # event: user_message; replay only, the recorded request of a turn
    text: str


class TextDelta(BaseModel, frozen=True):  # event: text_delta
    text: str


class ToolStarted(BaseModel, frozen=True):  # event: tool_started
    call_id: str
    tool: str
    arguments: dict[str, object]


class ToolFinished(BaseModel, frozen=True):  # event: tool_finished
    call_id: str
    tool: str
    status: Literal["ok", "error"]
    duration_ms: int
    summary: Coded
    result: dict[str, object] | None  # the tool's output model, serialised
    error: ToolError | None


class ApprovalRequired(BaseModel, frozen=True):  # event: approval_required
    approval_id: SubmissionId
    quote_id: QuoteId


class GroundingFlagged(BaseModel, frozen=True):  # event: grounding_flagged
    message_id: str
    values: list[str]  # the figures, as written in the answer


class StreamError(BaseModel, frozen=True):  # event: error
    code: str
    completed: list[str]  # tools that finished before the failure


class Done(BaseModel, frozen=True):  # event: done
    conversation_id: ConversationId
    message_id: str
    stop_reason: Literal["end_turn", "tool_limit", "budget", "error"]
    prompt_version: str


AgentEvent = (
    Started
    | UserMessage
    | TextDelta
    | ToolStarted
    | ToolFinished
    | ApprovalRequired
    | GroundingFlagged
    | StreamError
    | Done
)


class MessageView(BaseModel, frozen=True):
    message_id: str
    role: Literal["user", "assistant"]
    text: str
    tools: list[ToolFinished]
    flagged: list[str]
    created_at: datetime


class ConversationView(BaseModel, frozen=True):
    conversation_id: ConversationId
    messages: list[MessageView]


class AssistantFacade(Protocol):
    def chat(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> AsyncIterator[AgentEvent]: ...
    async def conversation(
        self, principal: Principal, conversation_id: ConversationId
    ) -> ConversationView: ...
    def replay(self, locale: Locale) -> AsyncIterator[AgentEvent]: ...
