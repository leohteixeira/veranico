"""The `documents` routes over HTTP: this module as `module.py` wires it, nothing else real.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/api/documents -m integration -q

The application is this module's router with the problem handlers and `http_auth` bound to
`FakeAccessFacade`; quotes come from `FakeQuotingFacade`, evidence bytes from
`FakeClimateFacade`, and the blobs live in a `GcsBlobStore` on the shared emulator. The fake
access facade numbers its workspaces from `ws-1` in every test, so each test gets a bucket
of its own, removed afterwards; nothing else in the emulator is touched.
"""

import contextlib
import io
import os
import socket
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from google.api_core.exceptions import NotFound
from pypdf import PdfReader

from tests.fakes.access import FakeAccessFacade
from tests.fakes.app import build_test_app
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.quoting import FakeQuotingFacade
from tests.fakes.settings import settings_for_tests
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import climate_with_dataset_of
from veranico.modules.documents import module as documents_module
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.infrastructure.blobs import GcsBlobStore, storage_client
from veranico.shared.infrastructure.http_auth import WORKSPACE_COOKIE
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import WorkspaceId

STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
NETCDF = b"\x89HDF\r\n\x1a\nfake evidence over HTTP"


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return " ".join(" ".join(page.extract_text() for page in reader.pages).split())


@dataclass(frozen=True)
class Visitor:
    """A browser with its workspace cookie, and an API key of the same workspace."""

    workspace_id: WorkspaceId
    browser: httpx.AsyncClient
    api_key: httpx.AsyncClient


@dataclass(frozen=True)
class DocumentsApi:
    app: FastAPI
    access: FakeAccessFacade
    quoting: FakeQuotingFacade
    climate: FakeClimateFacade
    blobs: GcsBlobStore
    bucket: str

    def client(self, **kwargs: object) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app)
        return httpx.AsyncClient(transport=transport, base_url="http://veranico.test", **kwargs)  # type: ignore[arg-type]  # headers or cookies, passed through

    async def visitor(self) -> Visitor:
        principal, cookie = await self.access.open_workspace(None)
        assert cookie is not None
        issued = await self.access.issue_api_key(principal)
        return Visitor(
            workspace_id=principal.workspace_id,
            browser=self.client(cookies={WORKSPACE_COOKIE: cookie}),
            api_key=self.client(headers={"Authorization": f"Bearer {issued.secret}"}),
        )

    def seed(self, quote: QuoteView, workspace_id: WorkspaceId) -> QuoteView:
        """Store the quote as a quote of that workspace."""
        return self.quoting.seed_quote(quote.model_copy(update={"workspace_id": workspace_id}))


@pytest.fixture
def api() -> Iterator[DocumentsApi]:
    host, _, port = STORAGE_HOST.removeprefix("http://").partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Cloud Storage emulator is not listening on {STORAGE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    bucket = f"veranico-documents-api-{uuid.uuid4().hex}"
    settings = settings_for_tests(
        storage_emulator_host=STORAGE_HOST, storage_bucket=bucket, blob_backend="gcs"
    )
    client = storage_client(settings)
    client.create_bucket(bucket)
    blobs = GcsBlobStore(client, bucket)
    access = FakeAccessFacade()
    quoting = FakeQuotingFacade()
    climate = climate_with_dataset_of(fixtures.rainfall_quote())
    climate.set_evidence(NETCDF)
    module = documents_module.build(
        documents_module.DocumentsDeps(
            settings=settings,
            clock=FixedClock(datetime(2026, 11, 11, 12, 0, tzinfo=UTC)),
            blobs=blobs,
            quoting=quoting,
            climate=climate,
            access=access,
        )
    )
    app = build_test_app(module.routers, access, settings=settings)
    yield DocumentsApi(
        app=app, access=access, quoting=quoting, climate=climate, blobs=blobs, bucket=bucket
    )
    # Remove only what this test created: its own objects, then its own bucket.
    with contextlib.suppress(NotFound):
        for blob in client.list_blobs(bucket):
            blob.delete()
        client.bucket(bucket).delete()
