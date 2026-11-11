"""The `quoting` routes over HTTP: the real module on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/api/quoting -m integration -q

The application is this module's router (built by `module.build`, as `bootstrap.py` does)
with the problem handlers and `http_auth` bound to a fake access facade; `climate` and
`pricing` are their fakes, the catalogue is fixed and the dispatcher only records. No other
module's implementation is involved.

The emulator is shared: every workspace id is random and its documents are deleted
afterwards, and the clock stands on a random instant decades in the past so the sweep,
which reads the whole outbox, never finds another run's records old enough to touch.
"""

import os
import secrets
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from google.cloud.firestore import AsyncClient

from tests.fakes import builders
from tests.fakes.access import FakeAccessFacade
from tests.fakes.app import build_test_app
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from tests.fakes.settings import settings_for_tests
from tests.integration.quoting.conftest import delete_workspace_documents
from tests.unit.quoting.world import FixedCatalog, RecordingDispatcher
from veranico.modules.quoting import module as quoting_module
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
INTERNAL_TOKEN = "test-internal-token"  # a fixed test string, not a secret
V1 = "/api/v1"


class UniqueAccess(FakeAccessFacade):
    """The fake, with workspace ids no other test run on the shared emulator can have."""

    def __init__(self) -> None:
        super().__init__()
        self._run = secrets.token_hex(8)
        self.workspaces: set[WorkspaceId] = set()

    async def open_workspace(self, cookie: str | None) -> tuple[Principal, str | None]:
        principal, new_cookie = await super().open_workspace(cookie)
        workspace_id = WorkspaceId(f"ws-api-{self._run}-{principal.workspace_id}")
        self.workspaces.add(workspace_id)
        return principal.model_copy(update={"workspace_id": workspace_id}), new_cookie


@dataclass
class Session:
    """One visitor: a browser with its workspace cookie and an API key of that workspace."""

    browser: httpx.AsyncClient
    api: httpx.AsyncClient
    workspace_id: WorkspaceId


@dataclass
class QuotingApi:
    app: FastAPI
    facade: QuotingFacade
    access: UniqueAccess
    climate: FakeClimateFacade
    pricing: FakePricingFacade
    dispatcher: RecordingDispatcher
    clock: FixedClock
    start: datetime
    firestore: AsyncClient
    _clients: list[httpx.AsyncClient] = field(default_factory=list)

    def client(self, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        """A client with an empty cookie jar. HTTPS: the workspace cookie is `Secure`."""
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="https://test", headers=headers
        )
        self._clients.append(client)
        return client

    async def session(self) -> Session:
        browser = self.client()
        opened = await browser.get(f"{V1}/quotes")  # any cookie route opens the workspace
        assert opened.status_code == 200
        (cookie,) = browser.cookies.values()
        principal, _ = await self.access.open_workspace(cookie)
        key = await self.access.issue_api_key(principal)
        api = self.client({"Authorization": f"Bearer {key.secret}"})
        return Session(browser=browser, api=api, workspace_id=principal.workspace_id)

    async def close(self) -> None:
        for client in self._clients:
            await client.aclose()
        for workspace_id in self.access.workspaces:
            await delete_workspace_documents(self.firestore, workspace_id)
        await close_firestore(self.firestore)


def quote_body(**location: Any) -> dict[str, Any]:
    """A valid `POST /quotes` body; keyword arguments replace fields of `location`."""
    return {
        "location": {"lat": builders.LAT, "lon": builders.LON, **location},
        "cover": builders.cover().model_dump(mode="json"),
        "simulation": {"n": 1_000, "seed": 7},
    }


@pytest.fixture
async def api() -> AsyncIterator[QuotingApi]:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    settings = settings_for_tests(
        firestore_emulator_host=FIRESTORE_HOST,
        delivery={"internal_auth": "token", "internal_token": INTERNAL_TOKEN},
    )
    start = datetime(1990, 1, 1, tzinfo=UTC) + timedelta(
        seconds=secrets.randbelow(20 * 365 * 86_400), microseconds=secrets.randbelow(10**6)
    )
    clock = FixedClock(start)
    firestore = firestore_client(settings)
    access = UniqueAccess()
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series())
    pricing = FakePricingFacade()
    pricing.add_dataset(dataset.dataset_id)
    dispatcher = RecordingDispatcher()
    module = quoting_module.build(
        quoting_module.QuotingDeps(
            settings=settings,
            clock=clock,
            firestore=firestore,
            pricing=pricing,
            climate=climate,
            access=access,
            carriers=FixedCatalog(),
            dispatcher=dispatcher,
        )
    )
    app = build_test_app(module.routers, access=access, settings=settings)
    context = QuotingApi(
        app=app,
        facade=module.facade,
        access=access,
        climate=climate,
        pricing=pricing,
        dispatcher=dispatcher,
        clock=clock,
        start=start,
        firestore=firestore,
    )
    yield context
    await context.close()
