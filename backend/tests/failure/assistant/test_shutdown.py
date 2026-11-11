"""Graceful shutdown (SPEC 17): an open stream ends with a final event."""

import pytest

from tests.api.assistant.conftest import CHAT, V1, AssistantApi, chat_body, sse_events
from veranico.modules.assistant.application.ports import ModelRequest
from veranico.modules.assistant.infrastructure.scripted_model import (
    Played,
    ScriptedModelClient,
    call_tool,
    say,
)

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-17-6")]


async def test_shutdown_ends_open_stream_with_final_event(api: AssistantApi) -> None:
    def signal_arrives_during_the_call(_: ModelRequest) -> Played:
        api.shutdown.set()  # SIGTERM, while the second model call of the turn is streaming
        return say("Sorriso is in Mato Grosso. It has a long dry season. Shall I price a cover?")

    model = ScriptedModelClient(
        [call_tool("resolve_location", {"query": "Sorriso"}), signal_arrives_during_the_call]
    )
    browser = api.browser(api.app_with(model))

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    # The call that was streaming is cut after the event it was sending.
    assert [name for name, _ in events] == [
        "started",
        "tool_started",
        "tool_finished",
        "text_delta",
        "error",
        "done",
    ]
    assert events[-2][1] == {"code": "shutting_down", "completed": ["resolve_location"]}
    assert events[-1][1]["stop_reason"] == "error"
    assert len(model.requests) == 2
    # The finished step is stored; the cut one is not.
    conversation_id = events[0][1]["conversation_id"]
    restored = (await browser.get(f"{V1}/conversations/{conversation_id}")).json()
    assert [tool["tool"] for tool in restored["messages"][-1]["tools"]] == ["resolve_location"]


async def test_a_turn_opened_during_shutdown_ends_at_once_with_the_final_event(
    api: AssistantApi,
) -> None:
    model = ScriptedModelClient([say("Never asked for.")])
    browser = api.browser(api.app_with(model))
    api.shutdown.set()

    response = await browser.post(CHAT, json=chat_body())

    events = sse_events(response.text)
    assert [name for name, _ in events] == ["started", "error", "done"]
    assert events[1][1] == {"code": "shutting_down", "completed": []}
    assert events[2][1]["stop_reason"] == "error"
    assert model.requests == []
