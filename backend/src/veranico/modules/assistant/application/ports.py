"""Ports of the turn loop. No SDK type appears here, in `application` or in `domain`.

`ConversationStore` keeps conversations durable (Firestore, or memory in unit tests).

`ModelClient` is the seam to the language model. A request is provider-neutral: the system
prompt, the messages as text, tool-call and tool-result blocks, and the tool definitions. An
adapter in `infrastructure` maps it to a provider (the Anthropic Messages API) or plays a
script (deterministic tests, `make dev` without a key).
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.domain.conversation import Entry
from veranico.shared.kernel.ids import ConversationId, Locale, WorkspaceId


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    call_id: str
    content: Mapping[str, object]  # the tool output, or `{error_code, message, retryable}`
    is_error: bool = False


Block = TextBlock | ToolCallBlock | ToolResultBlock


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """One message of the prompt. Tool calls live in assistant messages, results in user ones."""

    role: Literal["user", "assistant"]
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]  # JSON schema of the tool's input model


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model: str
    system: str
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolSpec, ...]
    max_output_tokens: int
    # "none": the model must answer in text. The wrap-up call uses it. The definitions stay in
    # the request because the history still holds tool blocks that refer to them.
    tool_use: Literal["auto", "none"] = "auto"


@dataclass(frozen=True, slots=True)
class ModelTextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]


ModelStop = Literal["end_turn", "tool_use", "max_tokens", "refused"]


@dataclass(frozen=True, slots=True)
class ModelCompleted:
    """Always the last event of a call that did not fail."""

    stop: ModelStop
    usage: ModelUsage


@dataclass(frozen=True, slots=True)
class ModelUsageSoFar:
    """What the provider has counted until now, for a call that may not reach its end.

    Optional. The loop charges the latest one when a call is cut by a disconnect or a
    shutdown, so tokens the provider billed are not lost. `ModelCompleted` replaces it.
    """

    usage: ModelUsage


ModelEvent = ModelTextDelta | ModelToolCall | ModelUsageSoFar | ModelCompleted


class ModelUnavailable(Exception):  # noqa: N818 - named after the code it becomes in the stream
    """The model call failed. `usage` is what the provider had reported until then, if anything.

    Not a domain error: the kernel owns those. The loop catches it and ends the stream with
    the kernel's `model_unavailable` code.
    """

    def __init__(self, detail: str | None = None, *, usage: ModelUsage | None = None) -> None:
        super().__init__(detail or "model_unavailable")
        self.usage = usage


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One user turn of a conversation. `message_id` names its assistant message."""

    turn: int
    message_id: str
    started_at: datetime
    finished_at: datetime | None = None
    flagged: tuple[str, ...] = ()  # figures the grounding check did not find, as written
    prompt_version: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationState:
    conversation_id: ConversationId
    workspace_id: WorkspaceId
    locale: Locale
    entries: tuple[Entry, ...]  # ascending `seq`
    turns: tuple[TurnRecord, ...]  # ascending `turn`
    total_tokens: int  # tokens of every model call of the conversation so far


class ConversationStore(Protocol):
    """Durable conversations, scoped to a workspace (SPEC 9.2).

    One turn writes a conversation at a time. `claim_turn` takes the claim, `append` renews
    its lease and `finish_turn` releases it; a claim whose lease ran out (a crashed turn) can
    be taken by the next turn. Without the claim two turns would interleave tool calls and
    results and leave a history the model rejects.
    """

    async def create(self, workspace_id: WorkspaceId, locale: Locale) -> ConversationId: ...

    async def claim_turn(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId, message_id: str
    ) -> int:
        """Open the next turn and return its number.

        Raises `not_found` for an unknown or expired conversation and for another workspace's,
        and `conflict` while another turn holds the claim.
        """
        ...

    async def append(self, conversation_id: ConversationId, entries: Sequence[Entry]) -> None:
        """Store the entries in one atomic write: all of them or none.

        Raises `conflict`, writing nothing, when an entry's `seq` is already stored.
        """
        ...

    async def finish_turn(
        self,
        conversation_id: ConversationId,
        message_id: str,
        flagged: Sequence[str],
        tokens: int,
        prompt_version: str,
    ) -> None:
        """Record the turn's outcome, add its tokens to the total and release its claim."""
        ...

    async def load(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId
    ) -> ConversationState:
        """Raises `not_found` for an unknown or expired conversation and another workspace's."""
        ...


class ModelClient(Protocol):
    def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        """Text deltas and tool calls as they arrive, then one `ModelCompleted`.

        Raises `ModelUnavailable` when the provider or the transport fails, before or after
        the first event. The loop closes the generator when it stops reading early (a
        disconnect, a shutdown), which is when an adapter releases its connection.
        """
        ...
