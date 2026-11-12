"""`ModelClient` over the Anthropic Messages API, streaming. The only file that imports the SDK.

What was checked, and where. Source: the `claude-api` skill bundled with Claude Code 2.1.322
(its model table is dated 2026-11-03; files `python/claude-api/streaming.md`,
`shared/model-migration.md` section "Migrating to Claude Haiku 5.5", `shared/prompt-caching.md`,
`shared/tool-use-concepts.md`, `shared/error-codes.md`), read on 2026-11-11, and the types of the
installed SDK, `anthropic` 2.8.0.

* Model. `claude-haiku-5-5` is a valid identifier, written without a date suffix. Context
  window 1,000,000 tokens, at most 128,000 output tokens. Prices per million tokens for a
  prompt of up to 100,000 tokens: US$ 0.10 input, US$ 0.50 output, cache read 0.1 times the
  input price, a 5-minute cache write 1.25 times. A longer prompt is billed at US$ 0.50 and
  US$ 2.50, which is why compaction keeps prompts far below 100,000 tokens. The prices used
  for the spend ceiling are the settings' (`access.model_prices`), not this file's.
* Request. `messages.create(..., stream=True)` returns the raw event stream. Tools are
  `{name, description, input_schema}`. A tool call is a `tool_use` block of an assistant
  message; its result is a `tool_result` block (`tool_use_id`, `content`, `is_error`) in the
  next user message, before any text of that message. `tool_choice` is `{"type": "auto"}` or
  `{"type": "none"}`; `none` is accepted while the history holds tool blocks and the tools
  stay in the request. Sampling parameters other than the defaults are rejected by this
  model, so none is sent. Messages of one role are already merged by the prompt builder.
* Stream. `message_start` (usage: input and cache tokens), then per content block
  `content_block_start`, `content_block_delta` (`text_delta` with `text`, `input_json_delta`
  with `partial_json`) and `content_block_stop`, then `message_delta` (`stop_reason`,
  cumulative `usage.output_tokens`) and `message_stop`.
* Stop reasons (SDK type `StopReason`): `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`,
  `pause_turn`, `refusal`, `model_context_window_exceeded`. `STOP_REASONS` maps each one.
* Usage: `input_tokens` (not cached), `cache_creation_input_tokens`,
  `cache_read_input_tokens`, `output_tokens`.
* Errors: every SDK error derives from `anthropic.APIError` (`APIConnectionError`,
  `APITimeoutError`, `APIStatusError` and its subclasses by status). The SDK's default
  timeout is 10 minutes and it retries a request twice (connection errors, 408, 409, 429,
  5xx), only before a response has started.

Decisions.

* Thinking is off (`thinking: {"type": "disabled"}`, accepted by this model at effort `high`
  or below). The model thinks by default, and a thinking block must be sent back unchanged
  and is rejected once anything before it changed. The port carries text and tool calls
  only, and compaction rewrites earlier results by design, so thinking blocks could not be
  replayed correctly. Effort is `medium`, the model's default, sent explicitly.
* Tool calls reach the loop only when the call ended with `tool_use`. A call cut by
  `max_tokens` or a refusal can hold a truncated tool input, which must never run.
* Tool inputs are not streamed eagerly (`eager_input_streaming` is left off): the inputs are
  small, and without it the API validates each input before sending it. The registry
  validates again.
* Prompt caching is on for the stable prefix: one breakpoint on the system block, which
  caches the tool definitions and the system prompt together (render order: tools, system,
  messages). The prefix is about 13,700 characters, several times the 512-token minimum of
  this model, and is byte-identical on every request.
* One retry, not the SDK's two, and the timeout of the settings: with the provisional 60
  seconds a call that never answers ends within the 3-minute lease of the conversation's
  claim. Nothing is retried once a stream has started.
* An error becomes `ModelUnavailable` described by its class and HTTP status only. The
  provider's message is never copied: it can quote the request.
"""

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import anthropic

from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelCompleted,
    ModelEvent,
    ModelMessage,
    ModelRequest,
    ModelStop,
    ModelTextDelta,
    ModelToolCall,
    ModelUnavailable,
    ModelUsageSoFar,
    TextBlock,
    ToolCallBlock,
)
from veranico.shared.infrastructure.settings import Settings

_log = logging.getLogger(__name__)

EFFORT: Final = "medium"
MAX_RETRIES: Final = 1

# Every stop reason of the Messages API as a stop of the port. `stop_sequence` and
# `pause_turn` cannot happen here (no stop sequence is sent, no server tool is declared) and
# end the call like `end_turn`. A full context window cuts the answer as `max_tokens` does.
STOP_REASONS: Final[Mapping[str, ModelStop]] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "pause_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "model_context_window_exceeded": "max_tokens",
    "refusal": "refused",
}


def provider_request(request: ModelRequest) -> dict[str, Any]:
    """The keyword arguments of `messages.create` for a request of the port."""
    return {
        "model": request.model,
        "max_tokens": request.max_output_tokens,
        "system": [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
            message
            for message in (_provider_message(item) for item in request.messages)
            if message["content"]
        ],
        "tools": [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in request.tools
        ],
        "tool_choice": {"type": "none" if request.tool_use == "none" else "auto"},
        "thinking": {"type": "disabled"},
        "output_config": {"effort": EFFORT},
        "stream": True,
    }


def _provider_message(message: ModelMessage) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for block in message.blocks:
        if isinstance(block, TextBlock):
            if block.text:  # the API rejects an empty text block
                content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCallBlock):
            content.append(
                {
                    "type": "tool_use",
                    "id": block.call_id,
                    "name": block.name,
                    "input": dict(block.arguments),
                }
            )
        else:
            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.call_id,
                # One spelling for one result, so a cached prefix keeps matching.
                "content": json.dumps(
                    block.content, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ),
            }
            if block.is_error:
                result["is_error"] = True
            content.append(result)
    return {"role": message.role, "content": content}


def usage_of(model: str, usage: object, earlier: ModelUsage | None = None) -> ModelUsage:
    """A provider usage object as `ModelUsage`.

    `message_delta` reports the output tokens and may leave the other counts unset; a count
    that is unset keeps the value of `earlier` (the usage of `message_start`).
    """

    def count(name: str, known: int) -> int:
        value = getattr(usage, name, None)
        return value if isinstance(value, int) else known

    base = earlier or ModelUsage(model=model, input_tokens=0, output_tokens=0)
    return ModelUsage(
        model=model,
        input_tokens=count("input_tokens", base.input_tokens),
        output_tokens=count("output_tokens", base.output_tokens),
        cache_read_tokens=count("cache_read_input_tokens", base.cache_read_tokens),
        cache_write_tokens=count("cache_creation_input_tokens", base.cache_write_tokens),
    )


@dataclass(slots=True)
class _ToolUse:
    call_id: str
    name: str
    json_parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StreamMapper:
    """Turns the provider's stream events into events of the port, one event at a time.

    `finish` closes the call: the tool calls, when the call ended asking for them, then
    `ModelCompleted`. A stream that ended without a stop reason was cut and raises.
    """

    model: str
    usage: ModelUsage | None = None
    _tools: dict[int, _ToolUse] = field(default_factory=dict)
    _stop: str | None = None

    def feed(self, event: Any) -> Iterator[ModelEvent]:
        kind = event.type
        if kind == "message_start":
            self.usage = usage_of(self.model, event.message.usage)
            yield ModelUsageSoFar(usage=self.usage)
        elif kind == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                self._tools[event.index] = _ToolUse(call_id=block.id, name=block.name)
        elif kind == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                if delta.text:
                    yield ModelTextDelta(text=delta.text)
            elif delta.type == "input_json_delta" and event.index in self._tools:
                self._tools[event.index].json_parts.append(delta.partial_json)
        elif kind == "message_delta":
            self._stop = event.delta.stop_reason
            self.usage = usage_of(self.model, event.usage, self.usage)
        # `content_block_stop`, `message_stop` and block kinds this adapter does not use
        # (thinking is off) carry nothing the port needs.

    def finish(self) -> Iterator[ModelEvent]:
        stop = STOP_REASONS.get(self._stop or "")
        if stop is None or self.usage is None:
            raise ModelUnavailable("the model stream ended without a stop reason", usage=self.usage)
        if stop == "tool_use":
            for index in sorted(self._tools):
                tool = self._tools[index]
                yield ModelToolCall(
                    call_id=tool.call_id, name=tool.name, arguments=_arguments(tool.json_parts)
                )
        yield ModelCompleted(stop=stop, usage=self.usage)


def _arguments(json_parts: list[str]) -> Mapping[str, object]:
    """The input of a tool call. Anything that is not a JSON object becomes an empty input,
    which the tool's input model rejects, so the model reads `invalid_arguments` and retries.
    """
    try:
        parsed = json.loads("".join(json_parts) or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def unavailable(error: BaseException, usage: ModelUsage | None = None) -> ModelUnavailable:
    """`ModelUnavailable` for a provider or transport error: its class and status, no text."""
    status = getattr(error, "status_code", None)
    detail = type(error).__name__ + (f" (HTTP {status})" if isinstance(status, int) else "")
    _log.warning(
        "model call failed",
        extra={"error_type": type(error).__name__, "status_code": status},
    )
    return ModelUnavailable(detail, usage=usage)


class _Client(Protocol):
    """What the adapter uses of `anthropic.AsyncAnthropic`: `await messages.create(**kwargs)`."""

    @property
    def messages(self) -> Any: ...


class AnthropicModelClient:
    def __init__(self, client: _Client) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "AnthropicModelClient":
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required by the anthropic model client")
        return cls(
            anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=settings.assistant.model_timeout_seconds,
                max_retries=MAX_RETRIES,
            )
        )

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        mapper = StreamMapper(model=request.model)
        try:
            # The SDK retries here, before any event exists; never after.
            provider_stream = await self._client.messages.create(**provider_request(request))
        except anthropic.APIError as error:
            raise unavailable(error) from None
        try:
            events: AsyncIterator[Any] = aiter(provider_stream)
            while True:
                try:
                    event = await anext(events)
                except StopAsyncIteration:
                    break
                except Exception as error:
                    # Only the SDK and its transport run inside this `try`: an API error sent
                    # in the stream, a dropped connection, a read timeout.
                    raise unavailable(error, mapper.usage) from None
                for mapped in mapper.feed(event):
                    yield mapped
            for mapped in mapper.finish():
                yield mapped
        finally:
            await provider_stream.close()
