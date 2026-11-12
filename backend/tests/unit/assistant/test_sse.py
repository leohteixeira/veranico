"""The wire format of the chat and replay streams (contracts section 8)."""

import json
from typing import get_args

import pytest

from veranico.modules.assistant.application.replay import EVENT_NAMES, Replays, parse_recording
from veranico.modules.assistant.contracts import (
    AgentEvent,
    ApprovalRequired,
    Done,
    GroundingFlagged,
    Started,
    StreamError,
    TextDelta,
    ToolError,
    ToolFinished,
    ToolStarted,
    UserMessage,
)
from veranico.modules.assistant.http.sse import encode
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import ConversationId, QuoteId, SubmissionId

CONVERSATION = ConversationId("conversation-1")

EVENTS: dict[str, AgentEvent] = {
    "started": Started(conversation_id=CONVERSATION, message_id="m1"),
    "user_message": UserMessage(text="line one\nline two"),
    "text_delta": TextDelta(text="first\n\nsecond"),
    "tool_started": ToolStarted(call_id="c1", tool="resolve_location", arguments={"query": "X"}),
    "tool_finished": ToolFinished(
        call_id="c1",
        tool="resolve_location",
        status="error",
        duration_ms=3,
        summary=Coded(code="tool.error", params={"error_code": "location_not_found"}),
        result=None,
        error=ToolError(error_code="location_not_found", message="no\nmatch", retryable=False),
    ),
    "approval_required": ApprovalRequired(approval_id=SubmissionId("s1"), quote_id=QuoteId("Q-1")),
    "grounding_flagged": GroundingFlagged(message_id="m1", values=["R$ 1,00"]),
    "error": StreamError(code="model_unavailable", completed=["resolve_location"]),
    "done": Done(
        conversation_id=CONVERSATION, message_id="m1", stop_reason="end_turn", prompt_version="v1"
    ),
}


@pytest.mark.req("R-9.1-5")
def test_each_event_type_encodes_to_its_name_and_single_line_json() -> None:
    assert {type(event) for event in EVENTS.values()} == set(get_args(AgentEvent))
    assert set(EVENT_NAMES) == set(get_args(AgentEvent))

    for name, event in EVENTS.items():
        encoded = encode(event).decode("utf-8")

        assert encoded.endswith("\n\n")
        name_line, data_line = encoded.removesuffix("\n\n").split("\n")  # exactly two lines
        assert name_line == f"event: {name}"
        assert data_line.startswith("data: ")
        assert json.loads(data_line.removeprefix("data: ")) == event.model_dump(mode="json")


@pytest.mark.req("R-9.1-5")
def test_non_ascii_text_survives_encoding() -> None:
    text = "O prêmio é R$ 12.345,67 — São João 🌧"

    encoded = encode(TextDelta(text=text))

    assert text.encode("utf-8") in encoded  # written as UTF-8, not as escapes
    assert json.loads(encoded.decode("utf-8").split("data: ", 1)[1]) == {"text": text}


@pytest.mark.req("R-9.6-2")
def test_a_recording_is_metadata_then_events() -> None:
    text = "\n".join(
        [
            json.dumps({"prompt_version": "v1"}),
            json.dumps({"event": "started", "data": {"conversation_id": "r", "message_id": "m"}}),
            json.dumps({"event": "user_message", "data": {"text": "Olá"}}),
        ]
    )

    metadata, events = parse_recording(text)

    assert metadata == {"prompt_version": "v1"}
    assert events == (
        Started(conversation_id=ConversationId("r"), message_id="m"),
        UserMessage(text="Olá"),
    )
    with pytest.raises(ValueError, match="metadata"):
        parse_recording(text.split("\n", 1)[1])
    with pytest.raises(KeyError):
        parse_recording(text + "\n" + json.dumps({"event": "unknown", "data": {}}))


@pytest.mark.req("R-9.6-2")
def test_the_packaged_recordings_load_for_both_locales() -> None:
    replays = Replays()

    for locale in ("en", "pt-BR"):
        events = replays.events(locale)
        assert isinstance(events[0], Started)
        assert isinstance(events[1], UserMessage)
        assert isinstance(events[-1], Done)
