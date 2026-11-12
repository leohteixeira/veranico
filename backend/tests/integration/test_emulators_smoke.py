"""The emulators of `compose.yaml` answer through the shared infrastructure helpers.

    docker compose up -d --wait firestore storage
    uv run pytest tests/integration/test_emulators_smoke.py -m integration -q

The emulators are shared by every test run, so each test writes under a fresh name and
never clears them.
"""

import contextlib
import os
import socket
import uuid

import pytest
from google.api_core.exceptions import Conflict

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.blobs import (
    BlobNotFoundError,
    BlobPreconditionError,
    GcsBlobStore,
    storage_client,
)
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.req("R-14-4")]

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
BUCKET = "veranico-smoke"


def _require_listening(name: str, address: str) -> None:
    """Fail at once when an emulator is down, instead of waiting out the client retries."""
    host, _, port = address.removeprefix("http://").partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the {name} emulator is not listening on {address}: "
            "run `docker compose up -d --wait firestore storage`"
        )


@pytest.fixture
def settings() -> Settings:
    _require_listening("Firestore", FIRESTORE_HOST)
    _require_listening("Cloud Storage", STORAGE_HOST)
    return settings_for_tests(
        firestore_emulator_host=FIRESTORE_HOST,
        storage_emulator_host=STORAGE_HOST,
        storage_bucket=BUCKET,
        blob_backend="gcs",
    )


@pytest.fixture
def store(settings: Settings) -> GcsBlobStore:
    client = storage_client(settings)
    with contextlib.suppress(Conflict):  # another run created it
        client.create_bucket(BUCKET)
    return GcsBlobStore(client, BUCKET)


async def test_firestore_document_is_written_and_read_back(settings: Settings) -> None:
    client = firestore_client(settings)
    document = client.collection("smoke_documents").document(uuid.uuid4().hex)
    try:
        await document.set({"name": "veranico", "count": 1})
        snapshot = await document.get()
        missing = await client.collection("smoke_documents").document(uuid.uuid4().hex).get()

        assert snapshot.exists
        assert snapshot.to_dict() == {"name": "veranico", "count": 1}
        assert not missing.exists
    finally:
        await document.delete()
        await close_firestore(client)


async def test_object_is_written_and_read_back_through_the_blob_store(store: GcsBlobStore) -> None:
    path = f"smoke/{uuid.uuid4().hex}/object.bin"

    generation = await store.put(path, b"first", content_type="application/octet-stream")
    blob = await store.get(path)

    assert blob.data == b"first"
    assert blob.generation == generation
    assert await store.exists(path)
    assert await store.list(path.rsplit("/", 1)[0]) == [path]
    with pytest.raises(BlobNotFoundError):
        await store.get(f"smoke/{uuid.uuid4().hex}/missing.bin")


async def test_a_write_with_a_stale_generation_precondition_fails(store: GcsBlobStore) -> None:
    path = f"smoke/{uuid.uuid4().hex}/object.bin"
    first = await store.put(path, b"first", if_generation_match=0)  # create only
    second = await store.put(path, b"second", if_generation_match=first)

    with pytest.raises(BlobPreconditionError):
        await store.put(path, b"third", if_generation_match=first)  # stale
    with pytest.raises(BlobPreconditionError):
        await store.put(path, b"again", if_generation_match=0)  # it already exists

    assert second != first
    assert (await store.get(path)).data == b"second"
