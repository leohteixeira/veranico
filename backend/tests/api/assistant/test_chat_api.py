import json
from pathlib import Path

import pytest

from tests.api.assistant.conftest import CHAT, V1, AssistantApi, build_api, chat_body, sse_events
from veranico.modules.assistant.infrastructure.scripted_model import call_tool, say

pytestmark = pytest.mark.integration

OPENAPI = Path(__file__).parents[3] / "openapi.json"
ROUTES = (f"{V1}/chat", f"{V1}/conversations/{{id}}", f"{V1}/replays/{{locale}}")


@pytest.mark.req("R-9.1-5", "R-11.2-1")
async def test_chat_streams_started_first_and_ends_with_done(api: AssistantApi) -> None:
    app = api.app(call_tool("resolve_location", {"query": "Sorriso"}), say("Found Sorriso."))
    browser = api.browser(app)

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = sse_events(response.text)
    assert [name for name, _ in events] == [
        "started",
        "tool_started",
        "tool_finished",
        "text_delta",
        "done",
    ]
    started, done = events[0][1], events[-1][1]
    assert set(started) == {"conversation_id", "message_id"}
    assert done["conversation_id"] == started["conversation_id"]
    assert done["message_id"] == started["message_id"]
    assert done["stop_reason"] == "end_turn"
    assert events[2][1]["status"] == "ok"

    # The next message of the same browser continues the conversation.
    more = api.browser(api.app(say("Anything else?")))
    more.cookies = browser.cookies
    # A second application over the same store: the conversation is durable, not in memory.
    response = await more.post(
        CHAT, json=chat_body("Thanks", conversation_id=started["conversation_id"])
    )
    assert response.status_code == 200, response.text
    assert sse_events(response.text)[0][1]["conversation_id"] == started["conversation_id"]


@pytest.mark.req("R-11.2-1")
async def test_chat_without_cookie_gets_a_workspace(api: AssistantApi) -> None:
    browser = api.browser(api.app(say("Hello.")))

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 200, response.text
    assert response.headers["set-cookie"].startswith("vr_ws=")
    assert sse_events(response.text)[-1][0] == "done"


@pytest.mark.req("R-10.3-6")
async def test_allowance_exhausted_is_a_problem_with_replay_available(api: AssistantApi) -> None:
    browser = api.browser(api.app(say("One."), say("Two."), say("Never asked for.")))
    for _ in range(2):  # the fake allows two conversations a day
        assert (await browser.post(CHAT, json=chat_body())).status_code == 200

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["code"] == "allowance_exhausted"
    assert problem["replay_available"] is True
    # Everything else keeps working: the replay is served to the same visitor.
    assert (await browser.get(f"{V1}/replays/en")).status_code == 200


@pytest.mark.req("R-10.3-6")
async def test_spend_ceiling_is_a_problem_with_replay_available(api: AssistantApi) -> None:
    browser = api.browser(api.app(say("Never asked for.")))
    api.access.ceiling_usd_micros = 0

    response = await browser.post(CHAT, json=chat_body())

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["code"] == "spend_ceiling_reached"
    assert problem["replay_available"] is True


@pytest.mark.req("R-10.3-5")
async def test_message_too_long_is_a_problem() -> None:
    api = build_api(access={"max_message_chars": 30})
    try:
        browser = api.browser(api.app(say("Never asked for.")))

        response = await browser.post(CHAT, json=chat_body("x" * 31))

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "message_too_long"
        assert "replay_available" not in problem
        assert "xxx" not in response.text
        assert [name for name, _ in api.access.calls if name == "admit_message"] == []
    finally:
        await api.close()


async def test_an_unknown_conversation_is_a_problem_and_not_a_stream(api: AssistantApi) -> None:
    browser = api.browser(api.app(say("Never asked for.")))

    response = await browser.post(CHAT, json=chat_body(conversation_id="no-such-conversation"))

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.req("R-11.2-1", "R-11.2-2", "R-11.2-3")
async def test_openapi_for_the_three_routes_is_unchanged_from_m0(api: AssistantApi) -> None:
    committed = json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"]

    served = api.app().openapi()["paths"]

    assert set(served) == set(ROUTES)
    for route in ROUTES:
        assert served[route] == committed[route], route
