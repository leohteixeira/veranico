"""The Anthropic adapter's mapping, without the network.

Stream events are built from the documented JSON shapes and validated by the SDK's own
event types, so a shape the SDK would not produce cannot be fed to the mapper. No test here
makes a request: the client is a stand-in whose `messages.create` returns prepared events.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, get_args

import anthropic
import httpx2
import pytest
from anthropic.types import RawMessageStreamEvent, StopReason
from pydantic import TypeAdapter

from tests.fakes.settings import settings_for_tests
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelCompleted,
    ModelEvent,
    ModelMessage,
    ModelRequest,
    ModelTextDelta,
    ModelToolCall,
    ModelUnavailable,
    ModelUsageSoFar,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)
from veranico.modules.assistant.infrastructure.anthropic_model import (
    EFFORT,
    MAX_RETRIES,
    STOP_REASONS,
    AnthropicModelClient,
    StreamMapper,
    provider_request,
    usage_of,
)

pytestmark = pytest.mark.req("R-9.1-1")

MODEL = "claude-haiku-5-5"
FAKE_KEY = "test-key-that-is-not-a-secret"
_EVENT = TypeAdapter[Any](RawMessageStreamEvent)

TOOL = ToolSpec(
    name="resolve_location",
    description="Find a place.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
)


def request(*messages: ModelMessage, tool_use: str = "auto") -> ModelRequest:
    return ModelRequest(
        model=MODEL,
        system="You are the assistant.",
        messages=messages,
        tools=(TOOL,),
        max_output_tokens=1024,
        tool_use=tool_use,  # type: ignore[arg-type]  # the tests pass one of the two literals
    )


def event(shape: dict[str, Any]) -> Any:
    return _EVENT.validate_python(shape)


def message_start(**usage: int) -> Any:
    return event(
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0, **usage},
            },
        }
    )


def text_block(index: int, *parts: str) -> list[Any]:
    return [
        event(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            }
        ),
        *[
            event(
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": part},
                }
            )
            for part in parts
        ],
        event({"type": "content_block_stop", "index": index}),
    ]


def tool_block(index: int, call_id: str, name: str, *json_parts: str) -> list[Any]:
    return [
        event(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "tool_use", "id": call_id, "name": name, "input": {}},
            }
        ),
        *[
            event(
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": part},
                }
            )
            for part in json_parts
        ],
        event({"type": "content_block_stop", "index": index}),
    ]


def message_end(stop_reason: str, output_tokens: int) -> list[Any]:
    return [
        event(
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            }
        ),
        event({"type": "message_stop"}),
    ]


def mapped(events: Sequence[Any]) -> list[ModelEvent]:
    mapper = StreamMapper(model=MODEL)
    out = [item for provider_event in events for item in mapper.feed(provider_event)]
    return [*out, *mapper.finish()]


def test_request_maps_to_provider_messages_and_tools() -> None:
    params = provider_request(
        request(
            ModelMessage(role="user", blocks=(TextBlock(text="Olá, São João"),)),
            ModelMessage(
                role="assistant",
                blocks=(
                    TextBlock(text="Looking."),
                    ToolCallBlock(call_id="toolu_1", name="resolve_location", arguments={"q": 1}),
                ),
            ),
        )
    )

    assert params["model"] == MODEL
    assert params["max_tokens"] == 1024
    assert params["stream"] is True
    # One cache breakpoint, on the system block: it covers the tools and the system prompt.
    assert params["system"] == [
        {
            "type": "text",
            "text": "You are the assistant.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert params["tools"] == [
        {
            "name": "resolve_location",
            "description": "Find a place.",
            "input_schema": TOOL.input_schema,
        }
    ]
    assert params["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Olá, São João"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "resolve_location",
                    "input": {"q": 1},
                },
            ],
        },
    ]
    assert params["tool_choice"] == {"type": "auto"}
    assert params["thinking"] == {"type": "disabled"}
    assert params["output_config"] == {"effort": EFFORT}
    # Nothing the model rejects or that would change the answer between requests.
    assert not {"temperature", "top_p", "top_k", "fallbacks"} & set(params)


def test_the_wrap_up_request_forbids_tools_and_keeps_their_definitions() -> None:
    params = provider_request(
        request(ModelMessage(role="user", blocks=(TextBlock(text="hi"),)), tool_use="none")
    )

    assert params["tool_choice"] == {"type": "none"}
    assert [tool["name"] for tool in params["tools"]] == ["resolve_location"]


def test_tool_result_and_tool_error_map_to_result_blocks() -> None:
    params = provider_request(
        request(
            ModelMessage(
                role="user",
                blocks=(
                    ToolResultBlock(call_id="toolu_1", content={"b": "São", "a": 1}),
                    ToolResultBlock(
                        call_id="toolu_2",
                        content={"error_code": "invalid_cover", "message": "m", "retryable": False},
                        is_error=True,
                    ),
                    TextBlock(text="And now?"),
                    TextBlock(text=""),
                ),
            ),
            ModelMessage(role="assistant", blocks=(TextBlock(text=""),)),
        )
    )

    assert params["messages"] == [
        {
            "role": "user",
            "content": [
                # Canonical JSON text: sorted keys, no spaces, UTF-8 kept.
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"a":1,"b":"São"}'},
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": '{"error_code":"invalid_cover","message":"m","retryable":false}',
                    "is_error": True,
                },
                {"type": "text", "text": "And now?"},
            ],
        }
        # The empty text block and the message it left empty are not sent.
    ]


def test_provider_stream_events_map_to_model_events() -> None:
    events = [
        message_start(input_tokens=120, cache_read_input_tokens=3000),
        *text_block(0, "Let me ", "look."),
        *tool_block(1, "toolu_1", "resolve_location", '{"query": "S', 'orriso"}'),
        *tool_block(2, "toolu_2", "get_weather_history"),
        *message_end("tool_use", 45),
    ]

    start = ModelUsage(model=MODEL, input_tokens=120, output_tokens=0, cache_read_tokens=3000)
    assert mapped(events) == [
        ModelUsageSoFar(usage=start),
        ModelTextDelta(text="Let me "),
        ModelTextDelta(text="look."),
        # Tool calls come once the call is known to have ended asking for them.
        ModelToolCall(call_id="toolu_1", name="resolve_location", arguments={"query": "Sorriso"}),
        ModelToolCall(call_id="toolu_2", name="get_weather_history", arguments={}),
        ModelCompleted(stop="tool_use", usage=start.model_copy(update={"output_tokens": 45})),
    ]


def test_a_thinking_block_and_other_unused_events_are_ignored() -> None:
    events = [
        message_start(input_tokens=5),
        event(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            }
        ),
        event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "hm"},
            }
        ),
        event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            }
        ),
        event({"type": "content_block_stop", "index": 0}),
        *text_block(1, "Hello."),
        *message_end("end_turn", 3),
    ]

    assert [type(item).__name__ for item in mapped(events)] == [
        "ModelUsageSoFar",
        "ModelTextDelta",
        "ModelCompleted",
    ]


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_a_cut_call_never_hands_out_its_tool_calls(stop_reason: str) -> None:
    events = [
        message_start(input_tokens=5),
        *tool_block(0, "toolu_1", "request_submission", '{"quote_id": "Q-1'),
        *message_end(stop_reason, 9),
    ]

    out = mapped(events)

    assert not any(isinstance(item, ModelToolCall) for item in out)
    assert isinstance(out[-1], ModelCompleted)
    assert out[-1].stop == STOP_REASONS[stop_reason]


def test_a_tool_input_that_is_not_a_json_object_becomes_an_empty_input() -> None:
    for parts in (('{"query": "S',), ("[1, 2]",), ('"text"',)):
        events = [
            message_start(input_tokens=5),
            *tool_block(0, "toolu_1", "resolve_location", *parts),
            *message_end("tool_use", 9),
        ]

        calls = [item for item in mapped(events) if isinstance(item, ModelToolCall)]

        assert calls == [ModelToolCall(call_id="toolu_1", name="resolve_location", arguments={})]


def test_every_documented_stop_reason_maps_to_a_port_stop() -> None:
    assert set(STOP_REASONS) == set(get_args(StopReason))  # the SDK's own list
    assert STOP_REASONS == {
        "end_turn": "end_turn",
        "stop_sequence": "end_turn",
        "pause_turn": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "model_context_window_exceeded": "max_tokens",
        "refusal": "refused",
    }
    for stop_reason, stop in STOP_REASONS.items():
        last = mapped([message_start(input_tokens=1), *message_end(stop_reason, 1)])[-1]
        assert isinstance(last, ModelCompleted)
        assert last.stop == stop


def test_a_stream_that_ends_without_a_stop_reason_is_a_failure_with_its_usage() -> None:
    mapper = StreamMapper(model=MODEL)
    for provider_event in [message_start(input_tokens=40), *text_block(0, "Half an ans")]:
        list(mapper.feed(provider_event))

    with pytest.raises(ModelUnavailable) as raised:
        list(mapper.finish())

    assert raised.value.usage == ModelUsage(model=MODEL, input_tokens=40, output_tokens=0)


def test_usage_maps_to_model_usage_including_cache_tokens() -> None:
    start = message_start(
        input_tokens=11, output_tokens=1, cache_creation_input_tokens=700, cache_read_input_tokens=5
    )
    (delta, _) = message_end("end_turn", 64)

    first = usage_of(MODEL, start.message.usage)
    last = usage_of(MODEL, delta.usage, first)

    assert first == ModelUsage(
        model=MODEL, input_tokens=11, output_tokens=1, cache_read_tokens=5, cache_write_tokens=700
    )
    # `message_delta` carries the output count; the counts it leaves unset are kept.
    assert last == first.model_copy(update={"output_tokens": 64})
    # The model of the usage is the configured one: it is the key of the price table.
    assert usage_of("configured-model", start.message.usage).model == "configured-model"


class FakeStream:
    def __init__(self, events: Sequence[Any], error: BaseException | None = None) -> None:
        self._events = events
        self._error = error
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[Any]:
        for provider_event in self._events:
            yield provider_event
        if self._error is not None:
            raise self._error

    async def close(self) -> None:
        self.closed = True


class FakeMessages:
    def __init__(self, outcome: FakeStream | BaseException) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class FakeClient:
    def __init__(self, outcome: FakeStream | BaseException) -> None:
        self.messages = FakeMessages(outcome)


async def drain(
    client: AnthropicModelClient, into: list[ModelEvent] | None = None
) -> list[ModelEvent]:
    """Read the stream to its end; `into` keeps what arrived when the stream raises midway."""
    seen: list[ModelEvent] = [] if into is None else into
    async for item in client.stream(
        request(ModelMessage(role="user", blocks=(TextBlock(text="hi"),)))
    ):
        seen.append(item)
    return seen


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls: type[anthropic.APIStatusError], status: int, text: str) -> BaseException:
    return cls(text, response=httpx2.Response(status, request=_REQUEST), body=None)


PROVIDER_ERRORS = [
    (status_error(anthropic.RateLimitError, 429, "rate limited"), "RateLimitError (HTTP 429)"),
    (
        status_error(anthropic.InternalServerError, 529, "overloaded"),
        "InternalServerError (HTTP 529)",
    ),
    (status_error(anthropic.AuthenticationError, 401, "bad key"), "AuthenticationError (HTTP 401)"),
    (status_error(anthropic.BadRequestError, 400, "bad request"), "BadRequestError (HTTP 400)"),
    (anthropic.APIConnectionError(request=_REQUEST), "APIConnectionError"),
    (anthropic.APITimeoutError(request=_REQUEST), "APITimeoutError"),
]


@pytest.mark.parametrize(("error", "detail"), PROVIDER_ERRORS, ids=[d for _, d in PROVIDER_ERRORS])
async def test_provider_and_transport_errors_become_model_unavailable(
    error: BaseException, detail: str
) -> None:
    # Before the stream starts: `create` raises.
    with pytest.raises(ModelUnavailable) as before:
        await drain(AnthropicModelClient(FakeClient(error)))
    assert str(before.value) == detail
    assert before.value.usage is None

    # After it started: the usage reported until then goes with the failure.
    stream = FakeStream([message_start(input_tokens=30), *text_block(0, "Half")], error)
    seen: list[ModelEvent] = []
    with pytest.raises(ModelUnavailable) as after:
        await drain(AnthropicModelClient(FakeClient(stream)), seen)
    assert str(after.value) == detail
    assert after.value.usage == ModelUsage(model=MODEL, input_tokens=30, output_tokens=0)
    assert seen[-1] == ModelTextDelta(text="Half")
    assert stream.closed


async def test_a_dropped_connection_mid_stream_becomes_model_unavailable() -> None:
    stream = FakeStream([message_start(input_tokens=30)], httpx2.ReadError("connection reset"))

    with pytest.raises(ModelUnavailable) as raised:
        await drain(AnthropicModelClient(FakeClient(stream)))

    assert str(raised.value) == "ReadError"
    assert stream.closed


async def test_a_complete_stream_is_closed_and_sends_the_mapped_request() -> None:
    stream = FakeStream(
        [message_start(input_tokens=30), *text_block(0, "Hello."), *message_end("end_turn", 2)]
    )
    fake = FakeClient(stream)

    seen = await drain(AnthropicModelClient(fake))

    assert [type(item).__name__ for item in seen] == [
        "ModelUsageSoFar",
        "ModelTextDelta",
        "ModelCompleted",
    ]
    assert stream.closed
    (call,) = fake.messages.calls
    assert call == provider_request(
        request(ModelMessage(role="user", blocks=(TextBlock(text="hi"),)))
    )


async def test_api_key_never_appears_in_error_text(caplog: pytest.LogCaptureFixture) -> None:
    # A provider message that quotes the key and the request, as a careless upstream could.
    leaking = status_error(
        anthropic.AuthenticationError, 401, f"invalid x-api-key {FAKE_KEY}: user said hello"
    )
    stream = FakeStream([message_start(input_tokens=1)], leaking)

    with caplog.at_level(logging.DEBUG):
        for outcome in (leaking, stream):
            with pytest.raises(ModelUnavailable) as raised:
                await drain(AnthropicModelClient(FakeClient(outcome)))
            error = raised.value
            assert FAKE_KEY not in str(error)
            assert FAKE_KEY not in repr(error)
            assert "hello" not in str(error)
            # No chained exception carries the provider's text along.
            assert error.__cause__ is None
            assert error.__suppress_context__

    assert FAKE_KEY not in caplog.text
    assert "hello" not in caplog.text
    assert "model call failed" in caplog.text


def test_the_client_is_built_from_the_settings() -> None:
    settings = settings_for_tests(
        anthropic_api_key=FAKE_KEY,
        assistant={"model_client": "anthropic", "model_timeout_seconds": 42.0},
    )

    client = AnthropicModelClient.from_settings(settings)

    sdk = client._client
    assert isinstance(sdk, anthropic.AsyncAnthropic)
    assert sdk.max_retries == MAX_RETRIES == 1
    assert sdk.timeout == 42.0
    assert FAKE_KEY not in repr(client)
    assert FAKE_KEY not in repr(sdk)


def test_the_client_refuses_to_be_built_without_a_key() -> None:
    settings = settings_for_tests(anthropic_api_key=None)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicModelClient.from_settings(settings)
