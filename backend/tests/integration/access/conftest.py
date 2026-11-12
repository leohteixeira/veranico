"""Fixtures of the `access` integration tests: a client on the shared Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/access -m integration -q

The emulator is shared by every agent and test run: each test writes documents under
random identifiers (or, for the date-keyed spend ledger, a date of its own) and nothing
here clears it.
"""

import os
import secrets
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock

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


@pytest.fixture
async def spend_clock(firestore: AsyncClient) -> AsyncIterator[FixedClock]:
    """A clock on a date no other test uses, one second before a UTC midnight.

    The spend ledger is keyed by date, so its documents are shared by everything that
    runs on the emulator. A random far-future date gives each test a ledger of its own
    (the day is at most the 20th, so a few days later is still the same month). The
    documents of that date are deleted afterwards; nothing else is touched.
    """
    start = datetime(
        3000 + secrets.randbelow(6000),
        1 + secrets.randbelow(12),
        1 + secrets.randbelow(20),
        23,
        59,
        59,
        tzinfo=UTC,
    )
    yield FixedClock(start)
    collection = firestore.collection("access_spend")
    await collection.document(f"month-{start:%Y-%m}").delete()
    for offset in range(5):
        await collection.document(f"day-{start + timedelta(days=offset):%Y-%m-%d}").delete()
