"""Ports of the turn loop. No SDK type appears here, in `application` or in `domain`.

`ModelClient` is the seam to the language model. A request is provider-neutral: the system
prompt, the messages as text, tool-call and tool-result blocks, and the tool definitions. An
adapter in `infrastructure` maps it to a provider (the Anthropic Messages API) or plays a
script (deterministic tests, `make dev` without a key).
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from veranico.modules.access.contracts import ModelUsage
from veranico.shared.kernel.errors import ModelUnavailableError


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


ModelEvent = ModelTextDelta | ModelToolCall | ModelCompleted


class ModelUnavailable(ModelUnavailableError):  # noqa: N818 - named after its code, as the port says
    """The model call failed. `usage` is what the provider had reported until then, if anything."""

    def __init__(self, detail: str | None = None, *, usage: ModelUsage | None = None) -> None:
        super().__init__(detail)
        self.usage = usage


class ModelClient(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Text deltas and tool calls as they arrive, then one `ModelCompleted`.

        Raises `ModelUnavailable` when the provider or the transport fails, before or after
        the first event.
        """
        ...
