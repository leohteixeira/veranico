"""Fixtures of the `access` integration tests: a client on the shared Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/access -m integration -q

The emulator is shared by every agent and test run: each test writes documents under
random identifiers (or, for the date-keyed spend ledger, a date of its own) and nothing
here clears it.
"""

import os
import socket
from collections.abc import AsyncIterator

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")


@pytest.fixture
async def firestore() -> AsyncIterator[AsyncClient]:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    client = firestore_client(settings_for_tests(firestore_emulator_host=FIRESTORE_HOST))
    yield client
    await close_firestore(client)
