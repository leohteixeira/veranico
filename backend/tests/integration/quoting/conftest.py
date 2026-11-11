"""Fixtures of the `quoting` integration tests: `QuotingService` on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/quoting -m integration -q

The emulator is shared by every agent and test run. Each test works in a workspace with a
random id and deletes the documents of that workspace afterwards; nothing here clears the
emulator. The sweep reads the whole outbox by status, so each test also gets a clock on a
random instant decades in the past: records written by anything else (dated today) are
then never old enough for this test's sweep to touch.
"""

import os
import secrets
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud.firestore import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from tests.fakes.settings import settings_for_tests
from tests.unit.quoting.world import FixedCatalog, RecordingDispatcher
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.quoting.application.facade import QuotingService
from veranico.modules.quoting.contracts import (
    ApprovalView,
    CreateQuote,
    Decision,
    QuoteLocationInput,
    QuoteView,
    Submission,
)
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.infrastructure.firestore_idempotency import (
    FirestoreIdempotencyStore,
)
from veranico.modules.quoting.infrastructure.firestore_outbox import FirestoreOutboxStore
from veranico.modules.quoting.infrastructure.firestore_quotes import FirestoreQuoteRepository
from veranico.modules.quoting.infrastructure.mapping import AUDIT, IDEMPOTENCY, OUTBOX, QUOTES
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId, QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
TTL = timedelta(days=14)
SWEEP_AGE_SECONDS = 60
RETRY_WINDOW_SECONDS = 3_600


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


class Env:
    """The whole facade over the Firestore adapters, in one fresh workspace."""

    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self.workspace_id = WorkspaceId(f"ws-it-{secrets.token_hex(8)}")
        self.browser = Principal(workspace_id=self.workspace_id, kind="browser")
        self.api_key = Principal(workspace_id=self.workspace_id, kind="api_key", key_id="key-1")
        self.stranger = Principal(
            workspace_id=WorkspaceId(f"ws-it-{secrets.token_hex(8)}"), kind="browser"
        )
        self.start = datetime(1990, 1, 1, tzinfo=UTC) + timedelta(
            seconds=secrets.randbelow(20 * 365 * 86_400), microseconds=secrets.randbelow(10**6)
        )
        self.clock = FixedClock(self.start)
        self.quotes = FirestoreQuoteRepository(client, ttl=TTL)
        self.idempotency = FirestoreIdempotencyStore(client, ttl=TTL)
        self.outbox = FirestoreOutboxStore(client)
        self.dispatcher = RecordingDispatcher()
        self.climate = FakeClimateFacade()
        dataset = self.climate.add_series(builders.daily_series())
        self.pricing = FakePricingFacade()
        self.pricing.add_dataset(dataset.dataset_id)
        self.service = QuotingService(
            quotes=self.quotes,
            idempotency=self.idempotency,
            outbox=self.outbox,
            climate=self.climate,
            pricing=self.pricing,
            carriers=FixedCatalog(),
            dispatcher=self.dispatcher,
            clock=self.clock,
            sweep_age_seconds=SWEEP_AGE_SECONDS,
            retry_window_seconds=RETRY_WINDOW_SECONDS,
        )

    def command(self, label: str | None = None) -> CreateQuote:
        return CreateQuote(
            location=QuoteLocationInput(lat=builders.LAT, lon=builders.LON, label=label),
            cover=builders.cover(),
            simulation=SimulationOptions(n=1_000),
        )

    async def draft(self, principal: Principal | None = None) -> QuoteView:
        return await self.service.create_quote(
            principal or self.api_key, self.command(), None, "api_client"
        )

    async def pending(self, principal: Principal | None = None) -> Submission:
        owner = principal or self.api_key
        quote = await self.draft(owner)
        return await self.service.request_submission(owner, quote.quote_id, "carrier-1", "agent")

    async def approved(self) -> ApprovalView:
        submission = await self.pending()
        return await self.service.decide(
            self.browser, submission.submission_id, Decision(approve=True)
        )

    async def never_enqueued(self) -> ApprovalView:
        """An approval whose enqueue failed: committed, with the record still `pending`."""
        self.dispatcher.failure = RuntimeError("queue unavailable")
        approval = await self.approved()
        self.dispatcher.failure = None
        return approval

    async def view(self, quote_id: QuoteId) -> QuoteView:
        return await self.service.get_quote(self.browser, quote_id)

    async def record_of(self, quote_id: QuoteId) -> OutboxRecord:
        quote = await self.quotes.get(quote_id)
        assert quote is not None
        assert quote.current_event_id is not None
        record = await self.outbox.get(quote.current_event_id)
        assert record is not None
        return record

    async def event_of(self, quote_id: QuoteId) -> EventId:
        return (await self.record_of(quote_id)).event_id

    async def audit_codes(self, quote_id: QuoteId) -> list[str]:
        return [entry.action.code for entry in await self.quotes.audit(quote_id)]

    async def outbox_documents(self) -> list[str]:
        """The ids of the outbox documents of this workspace's quotes."""
        found = []
        for quote in await self.quotes.list_for_workspace(self.workspace_id):
            query = self.client.collection(OUTBOX).where(
                filter=FieldFilter("quote_id", "==", quote.quote_id)
            )
            found.extend([snapshot.id async for snapshot in query.stream()])
        return found

    async def clean(self) -> None:
        """Delete what the two workspaces of this test wrote, and nothing else."""
        for workspace_id in (self.workspace_id, self.stranger.workspace_id):
            owned = FieldFilter("workspace_id", "==", workspace_id)
            async for quote in self.client.collection(QUOTES).where(filter=owned).stream():
                async for entry in quote.reference.collection(AUDIT).stream():
                    await entry.reference.delete()
                events = self.client.collection(OUTBOX).where(
                    filter=FieldFilter("quote_id", "==", quote.id)
                )
                async for event in events.stream():
                    await event.reference.delete()
                await quote.reference.delete()
            async for key in self.client.collection(IDEMPOTENCY).where(filter=owned).stream():
                await key.reference.delete()


@pytest.fixture
async def env(firestore: AsyncClient) -> AsyncIterator[Env]:
    environment = Env(firestore)
    yield environment
    await environment.clean()
