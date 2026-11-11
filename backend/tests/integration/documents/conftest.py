"""Fixtures of the `documents` integration tests: a `GcsBlobStore` on the shared emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/documents -m integration -q

The emulator is shared by every agent and test run. Each test works under a fresh workspace
id, which is a fresh prefix `documents/<workspace_id>/`, and nothing here clears the bucket.
"""

import contextlib
import os
import socket
import uuid

import pytest
from google.api_core.exceptions import Conflict

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.blobs import GcsBlobStore, storage_client

STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
BUCKET = "veranico-documents-tests"


@pytest.fixture
def blobs() -> GcsBlobStore:
    host, _, port = STORAGE_HOST.removeprefix("http://").partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Cloud Storage emulator is not listening on {STORAGE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    client = storage_client(
        settings_for_tests(
            storage_emulator_host=STORAGE_HOST, storage_bucket=BUCKET, blob_backend="gcs"
        )
    )
    with contextlib.suppress(Conflict):  # another run created it
        client.create_bucket(BUCKET)
    return GcsBlobStore(client, BUCKET)


@pytest.fixture
def workspace_id() -> str:
    """A workspace no other test uses: its documents get a prefix of their own."""
    return f"ws-{uuid.uuid4().hex}"
