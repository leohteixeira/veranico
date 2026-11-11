"""The model API failing mid-turn (SPEC 16.3): the stream says what was completed."""

import pytest

from tests.api.assistant.conftest import CHAT, V1, AssistantApi, chat_body, sse_events
from tests.unit.assistant.tools import kit
from tests.unit.assistant.turn_kit import usage
from veranico.modules.assistant.application.ports import ModelTextDelta
from veranico.modules.assistant.infrastructure.scripted_model import (
    FailAfter,
    ScriptedModelClient,
    call_tool,
    say,
    tool_results,
)

pytestmark = [
    pytest.mark.failure,
    pytest.mark.integration,
    pytest.mark.req("R-9.1-6", "R-16.3-7"),
]

SORRISO = {"query": "Sorriso"}
POINT = {"lat": kit.SORRISO.lat, "lon": kit.SORRISO.lon}


async def test_model_fails_before_any_output(api: AssistantApi) -> None:
    browser = api.browser(api.app(FailAfter(), say("Back again.")))

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    assert [name for name, _ in events] == ["started", "error", "done"]
    assert events[1][1] == {"code": "model_unavailable", "completed": []}
    assert events[2][1]["stop_reason"] == "error"

    # The conversation stays usable: the next turn on it answers.
    conversation_id = events[0][1]["conversation_id"]
    again = await browser.post(CHAT, json=chat_body("Try again", conversation_id=conversation_id))
    assert again.status_code == 200, again.text
    names = [name for name, _ in sse_events(again.text)]
    assert names == ["started", "text_delta", "done"]
    restored = (await browser.get(f"{V1}/conversations/{conversation_id}")).json()
    assert [message["role"] for message in restored["messages"]] == ["user", "user", "assistant"]


async def test_model_fails_after_two_tools(api: AssistantApi) -> None:
    model = ScriptedModelClient(
        [
            call_tool("resolve_location", SORRISO, call_id="c1", usage=usage(10)),
            call_tool("get_weather_history", POINT, call_id="c2", usage=usage(20)),
            FailAfter(events=(ModelTextDelta(text="The history shows "),), usage=usage(7)),
            say("Here is the rest."),
        ]
    )
    browser = api.browser(api.app_with(model))

    response = await browser.post(CHAT, json=chat_body())

    events = sse_events(response.text)
    assert [name for name, _ in events] == [
        "started",
        "tool_started",
        "tool_finished",
        "tool_started",
        "tool_finished",
        "text_delta",
        "error",
        "done",
    ]
    assert events[-2][1] == {
        "code": "model_unavailable",
        "completed": ["resolve_location", "get_weather_history"],
    }
    assert events[-1][1]["stop_reason"] == "error"
    # The usage known at the failure is charged, with the two finished calls.
    recorded = [arguments[0] for name, arguments in api.access.calls if name == "record_spend"]
    assert recorded == [usage(10), usage(20), usage(7)]

    # The two finished steps are stored, the interrupted one is not.
    conversation_id = events[0][1]["conversation_id"]
    restored = (await browser.get(f"{V1}/conversations/{conversation_id}")).json()
    assistant = restored["messages"][-1]
    assert [tool["tool"] for tool in assistant["tools"]] == [
        "resolve_location",
        "get_weather_history",
    ]
    assert assistant["text"] == ""
    # The stored history is a valid model input: the next turn sends it and gets an answer.
    again = await browser.post(CHAT, json=chat_body("Go on", conversation_id=conversation_id))
    assert [name for name, _ in sse_events(again.text)][-1] == "done"
    assert [name for name, _ in tool_results(model.requests[-1])] == [
        "resolve_location",
        "get_weather_history",
    ]
