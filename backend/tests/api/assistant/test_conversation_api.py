import pytest

from tests.api.assistant.conftest import CHAT, V1, AssistantApi, chat_body, sse_events
from veranico.modules.assistant.infrastructure.scripted_model import call_tool, say

pytestmark = [pytest.mark.integration, pytest.mark.req("R-11.2-2")]


async def test_conversation_restores_messages_tools_and_flags(api: AssistantApi) -> None:
    app = api.app(
        call_tool("price_cover", api.tools.price_arguments(), text="Pricing it."),
        say("The premium is R$ 99,999.00."),  # a figure no tool returned
    )
    browser = api.browser(app)
    events = sse_events((await browser.post(CHAT, json=chat_body("Price my cover"))).text)
    started = events[0][1]
    (tool_finished,) = (data for name, data in events if name == "tool_finished")
    (flagged,) = (data for name, data in events if name == "grounding_flagged")
    streamed_text = "".join(data["text"] for name, data in events if name == "text_delta")

    response = await browser.get(f"{V1}/conversations/{started['conversation_id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"] == started["conversation_id"]
    user, assistant = body["messages"]
    assert (user["role"], user["text"]) == ("user", "Price my cover")
    assert (user["tools"], user["flagged"]) == ([], [])
    # The assistant message is what the stream showed, under the id the stream announced.
    assert assistant["role"] == "assistant"
    assert assistant["message_id"] == started["message_id"] == flagged["message_id"]
    assert assistant["text"] == streamed_text
    assert assistant["tools"] == [tool_finished]
    assert assistant["flagged"] == flagged["values"] == ["R$ 99,999.00"]


async def test_conversation_of_another_workspace_is_not_found(api: AssistantApi) -> None:
    app = api.app(say("Hello."))
    owner, stranger = api.browser(app), api.browser(app)
    events = sse_events((await owner.post(CHAT, json=chat_body())).text)
    url = f"{V1}/conversations/{events[0][1]['conversation_id']}"

    response = await stranger.get(url)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"
    assert (await owner.get(url)).status_code == 200


async def test_an_unknown_conversation_is_not_found(api: AssistantApi) -> None:
    response = await api.browser(api.app()).get(f"{V1}/conversations/no-such-conversation")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
