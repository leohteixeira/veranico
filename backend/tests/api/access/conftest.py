"""The `access` routes over HTTP, backed by the real facade on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/api/access -m integration -q

The application is this module's router with the problem handlers and `http_auth` bound to
the real `AccessFacade`. Secrets are generated per test, never written in a file. The
emulator is shared: every document a test writes has a random identifier, and the clock
stands on a random far-future date so the date-keyed spend ledger read by `admit_message`
is empty and belongs to this test alone.
"""

import os
import secrets
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from tests.fakes.app import build_test_app
from tests.fakes.settings import settings_for_tests
from veranico.modules.access import module as access_module
from veranico.modules.access.contracts import AccessFacade
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
ADDRESS = "203.0.113.57"  # a documentation address (RFC 5737)


@dataclass(frozen=True)
class AccessApi:
    app: FastAPI
    facade: AccessFacade
    clock: FixedClock
    allowance_code: str
    browser: Callable[[], httpx.AsyncClient]


@pytest.fixture
async def api() -> AsyncIterator[AccessApi]:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    allowance_code = secrets.token_urlsafe(12)
    settings = settings_for_tests(
        firestore_emulator_host=FIRESTORE_HOST,
        cookie_signing_secret=secrets.token_hex(32),
        access={"ip_hash_salt": secrets.token_hex(32), "allowance_code": allowance_code},
    )
    clock = FixedClock(
        datetime(
            3000 + secrets.randbelow(6000),
            1 + secrets.randbelow(12),
            1 + secrets.randbelow(20),
            12,
            0,
            tzinfo=UTC,
        )
    )
    firestore = firestore_client(settings)
    module = access_module.build(
        access_module.AccessDeps(settings=settings, clock=clock, firestore=firestore)
    )
    app = build_test_app(module.routers, access=module.facade, settings=settings)
    clients: list[httpx.AsyncClient] = []

    def browser() -> httpx.AsyncClient:
        """A browser of its own: an empty cookie jar, behind the documentation address.

        HTTPS, because outside development the workspace cookie is `Secure`.
        """
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://test",
            headers={"X-Forwarded-For": ADDRESS},
        )
        clients.append(client)
        return client

    yield AccessApi(
        app=app, facade=module.facade, clock=clock, allowance_code=allowance_code, browser=browser
    )
    for client in clients:
        await client.aclose()
    await close_firestore(firestore)
