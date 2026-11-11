"""The SSE client disconnecting mid-turn (SPEC 16.3).

The application is driven through ASGI directly, because a disconnect is something the
server tells the application. Both ways a server can tell it are covered: the ASGI spec the
installed uvicorn announces (2.3: the application reads `http.disconnect`, and Starlette
cancels the stream) and the newer one (2.4: sending to a closed connection fails).
"""

import asyncio
import json
from collections.abc import AsyncGenerator, MutableMapping
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from tests.api.assistant.conftest import CHAT, V1, AssistantApi, chat_body, sse_events
from tests.unit.assistant.turn_kit import usage
from veranico.modules.assistant.application.ports import (
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelTextDelta,
    ModelToolCall,
    ModelUsageSoFar,
)

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-16.3-8")]


class ToolThenHang:
    """Call 1 asks for a tool. Call 2 sends text and never ends. Later calls answer."""

    def __init__(self) -> None:
        self.calls = 0
        self.second_call_closed = False

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        self.calls += 1
        if self.calls == 1:
            yield ModelToolCall(
                call_id="c1", name="resolve_location", arguments={"query": "Sorriso"}
            )
            yield ModelCompleted(stop="tool_use", usage=usage(10))
        elif self.calls == 2:
            try:
                yield ModelUsageSoFar(usage=usage(5))
                yield ModelTextDelta(text="Sorriso is in ")
                await asyncio.Event().wait()
            finally:
                self.second_call_closed = True
        else:
            yield ModelTextDelta(text="Welcome back.")
            yield ModelCompleted(stop="end_turn", usage=usage(1))


class Connection:
    """One `POST /chat` whose client goes away when the first text arrives."""

    def __init__(self, spec_version: str) -> None:
        self.spec_version = spec_version
        self.body = b""
        self.headers: dict[str, str] = {}
        self._request_sent = False
        self._gone = asyncio.Event()

    def scope(self, payload: bytes) -> dict[str, Any]:
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": self.spec_version},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": CHAT,
            "raw_path": CHAT.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
            "client": ("203.0.113.9", 50_000),  # a documentation address (RFC 5737)
            "server": ("test", 443),
        }

    async def run(self, app: FastAPI) -> None:
        payload = json.dumps(chat_body()).encode()

        async def receive() -> dict[str, Any]:
            if not self._request_sent:
                self._request_sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await self._gone.wait()
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.headers = {k.decode(): v.decode() for k, v in message["headers"]}
                return
            chunk = message.get("body", b"")
            if b"event: text_delta" in chunk:
                self._gone.set()  # the client is gone: this chunk never arrives
                if self.spec_version == "2.4":
                    raise OSError("the client closed the connection")
                return
            self.body += chunk

        call = asyncio.wait_for(app(self.scope(payload), receive, send), timeout=10)
        if self.spec_version == "2.4":
            with pytest.raises(ClientDisconnect):
                await call
        else:
            await call


async def settled(api: AssistantApi) -> None:
    """Wait, bounded, until the cancelled turn has charged its last call and released."""
    for _ in range(300):
        charged = [name for name, _ in api.access.calls if name == "record_spend"]
        if len(charged) == 2:
            await asyncio.sleep(0.2)  # the release of the claim follows the charge
            return
        await asyncio.sleep(0.01)
    pytest.fail("the cancelled turn was never charged")


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_client_disconnects_mid_turn(api: AssistantApi, spec_version: str) -> None:
    model = ToolThenHang()
    app = api.app_with(model)
    connection = Connection(spec_version)

    await connection.run(app)
    await settled(api)

    events = sse_events(connection.body.decode())
    assert [name for name, _ in events] == ["started", "tool_started", "tool_finished"]
    # The open model call was closed and no further one was made.
    assert model.second_call_closed
    assert model.calls == 2
    # Spend is recorded: the finished call, and what the cut call had used until then.
    recorded = [arguments[0] for name, arguments in api.access.calls if name == "record_spend"]
    assert recorded == [usage(10), usage(5)]

    # The completed step is stored, the cut one is not, and the claim is released.
    cookie = connection.headers["set-cookie"].split(";", 1)[0]
    conversation_id = events[0][1]["conversation_id"]
    browser = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test", headers={"Cookie": cookie}
    )
    try:
        restored = (await browser.get(f"{V1}/conversations/{conversation_id}")).json()
        user, assistant = restored["messages"]
        assert user["role"] == "user"
        assert [tool["tool"] for tool in assistant["tools"]] == ["resolve_location"]
        assert assistant["text"] == ""

        again = await browser.post(CHAT, json=chat_body("Hello?", conversation_id=conversation_id))
        assert again.status_code == 200, again.text
        names = [name for name, _ in sse_events(again.text)]
        assert names == ["started", "text_delta", "done"]
        assert model.calls == 3
    finally:
        await browser.aclose()
