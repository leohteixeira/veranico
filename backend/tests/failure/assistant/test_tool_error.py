"""A failing dependency of a tool (SPEC 9.1): the model reads the error, HTTP never sees it."""

import pytest

from tests.api.assistant.conftest import CHAT, AssistantApi, chat_body, sse_events
from tests.unit.assistant.tools import kit
from veranico.modules.assistant.infrastructure.scripted_model import (
    ScriptedModelClient,
    call_tool,
    say,
    tool_results,
)
from veranico.shared.kernel.errors import WeatherSourceUnavailableError

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-9.1-3")]


async def test_tool_error_is_surfaced_to_the_model(api: AssistantApi) -> None:
    model = ScriptedModelClient(
        [
            call_tool("get_weather_history", {"lat": kit.SORRISO.lat, "lon": kit.SORRISO.lon}),
            say("The weather source is not answering; please try again in a moment."),
        ]
    )
    browser = api.browser(api.app_with(model))
    api.tools.climate.fail_with(WeatherSourceUnavailableError("upstream timed out"))

    response = await browser.post(CHAT, json=chat_body())

    # Nothing is raised to the HTTP layer: the stream is a normal turn.
    assert response.status_code == 200, response.text
    events = sse_events(response.text)
    assert [name for name, _ in events] == [
        "started",
        "tool_started",
        "tool_finished",
        "text_delta",
        "done",
    ]
    finished = events[2][1]
    assert finished["status"] == "error"
    assert finished["result"] is None
    assert finished["error"] == {
        "error_code": "weather_source_unavailable",
        "message": "upstream timed out",
        "retryable": True,
    }
    assert finished["summary"] == {
        "code": "tool.error",
        "params": {"error_code": "weather_source_unavailable"},
    }
    assert events[-1][1]["stop_reason"] == "end_turn"
    # The next model request carries the error as the result of the call.
    ((name, block),) = tool_results(model.requests[1])
    assert name == "get_weather_history"
    assert block.is_error
    assert block.content == finished["error"]
