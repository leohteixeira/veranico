"""The `assistant` routes over HTTP: the real module on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/api/assistant -m integration -q

The application is this module's router (built by `module.build`, as `bootstrap.py` does)
with the problem handlers and `http_auth` bound to a fake access facade. The six neighbour
modules are their fakes and the model is scripted. Conversations get random identifiers, so
the shared emulator needs no clearing.
"""

import asyncio
import json
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.fakes.access import FakeAccessFacade
from tests.fakes.app import build_test_app
from tests.fakes.settings import settings_for_tests
from tests.unit.assistant.tools.kit import Kit, build_kit
from veranico.modules.assistant import module as assistant_module
from veranico.modules.assistant.infrastructure.scripted_model import ScriptedModelClient, Step
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import SystemClock

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
V1 = "/api/v1"
CHAT = f"{V1}/chat"

Event = tuple[str, dict[str, Any]]


def sse_events(body: str) -> list[Event]:
    """The events of a stream as `(name, data)`. Fails on anything that is not the wire format."""
    events: list[Event] = []
    for block in body.split("\n\n"):
        if not block:
            continue
        name_line, data_line = block.split("\n")
        assert name_line.startswith("event: ")
        assert data_line.startswith("data: ")
        events.append((name_line.removeprefix("event: "), json.loads(data_line[6:])))
    return events


def chat_body(message: str = "A soy farm near Sorriso", **fields: Any) -> dict[str, Any]:
    return {"conversation_id": None, "message": message, "locale": "en", **fields}


@dataclass
class AssistantApi:
    tools: Kit
    access: FakeAccessFacade
    settings_overrides: dict[str, Any]
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    _closers: list[Any] = field(default_factory=list)

    def app(self, *steps: Step) -> FastAPI:
        """The module with a model that plays `steps`, one per model call."""
        settings = settings_for_tests(
            firestore_emulator_host=FIRESTORE_HOST, **self.settings_overrides
        )
        firestore = firestore_client(settings)
        self._closers.append(lambda: close_firestore(firestore))
        module = assistant_module.build(
            assistant_module.AssistantDeps(
                settings=settings,
                clock=SystemClock(),
                firestore=firestore,
                access=self.access,
                climate=self.tools.climate,
                pricing=self.tools.pricing,
                quoting=self.tools.quoting,
                carriers=self.tools.carriers,
                documents=self.tools.documents,
                model_client=ScriptedModelClient(steps),
                shutdown=self.shutdown,
            )
        )
        return build_test_app(module.routers, access=self.access, settings=settings)

    def browser(self, app: FastAPI) -> httpx.AsyncClient:
        """A browser of its own: an empty cookie jar. HTTPS: the workspace cookie is `Secure`."""
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test")
        self._closers.append(client.aclose)
        return client

    async def close(self) -> None:
        for close in self._closers:
            await close()


def build_api(**settings_overrides: Any) -> AssistantApi:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    return AssistantApi(
        tools=build_kit(), access=FakeAccessFacade(), settings_overrides=settings_overrides
    )


@pytest.fixture
async def api() -> AsyncIterator[AssistantApi]:
    context = build_api()
    yield context
    await context.close()
