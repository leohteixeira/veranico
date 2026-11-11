"""The quoting use cases wired over the in-memory stores and the fakes, for unit tests."""

from datetime import UTC, datetime

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from tests.unit.quoting.memory import (
    MemoryIdempotencyStore,
    MemoryOutboxStore,
    MemoryQuoteRepository,
)
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.quoting.application.approvals import ApprovalService, OutboxEnqueuer
from veranico.modules.quoting.application.facade import QuotingService
from veranico.modules.quoting.application.quotes import QuoteService
from veranico.modules.quoting.contracts import (
    ApprovalView,
    CarrierInfo,
    CreateQuote,
    Decision,
    DeliveryState,
    QuoteLocationInput,
    QuoteView,
    Submission,
)
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId
from veranico.shared.kernel.principal import Principal

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
SWEEP_AGE_SECONDS = 60
RETRY_WINDOW_SECONDS = 3_600
BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
API_KEY = Principal(workspace_id=WorkspaceId("ws-1"), kind="api_key", key_id="key-1")
STRANGER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")
STRANGER_KEY = Principal(workspace_id=WorkspaceId("ws-2"), kind="api_key", key_id="key-2")


class FixedCatalog:
    """A carrier catalogue with the two carriers of the builders."""

    def __init__(self) -> None:
        self._carriers = {carrier.carrier_id: carrier for carrier in builders.CARRIERS}

    def get(self, carrier_id: str) -> CarrierInfo | None:
        return self._carriers.get(carrier_id)

    def all(self) -> list[CarrierInfo]:
        return list(self._carriers.values())


class RecordingDispatcher:
    """Records every event id handed over; `failure` makes the next calls raise it."""

    def __init__(self) -> None:
        self.enqueued: list[EventId] = []
        self.failure: Exception | None = None
        self.fail_for: set[EventId] = set()

    async def enqueue(self, event_id: EventId) -> None:
        if self.failure is not None:
            raise self.failure
        if event_id in self.fail_for:
            raise RuntimeError("queue unavailable")
        self.enqueued.append(event_id)


class World:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.outbox = MemoryOutboxStore()
        self.quotes = MemoryQuoteRepository(self.outbox)
        self.dispatcher = RecordingDispatcher()
        self.catalog = FixedCatalog()
        self.sweeps = 0
        self.sweep_failure: Exception | None = None
        self._events = 0
        self._submissions = 0
        climate = FakeClimateFacade()
        dataset = climate.add_series(builders.daily_series())
        pricing = FakePricingFacade()
        pricing.add_dataset(dataset.dataset_id)
        self.quoting = QuoteService(
            quotes=self.quotes,
            idempotency=MemoryIdempotencyStore(),
            climate=climate,
            pricing=pricing,
            clock=self.clock,
        )
        self.enqueuer = OutboxEnqueuer(
            outbox=self.outbox, dispatcher=self.dispatcher, clock=self.clock
        )
        self.approvals = ApprovalService(
            quotes=self.quotes,
            carriers=self.catalog,
            enqueuer=self.enqueuer,
            clock=self.clock,
            sweep=self.approvals_sweep,
            new_submission=self._next_submission,
            new_event=self._next_event,
        )
        # The whole facade over the same stores, with the real sweep behind `list_approvals`.
        self.service = QuotingService(
            quotes=self.quotes,
            idempotency=MemoryIdempotencyStore(),
            outbox=self.outbox,
            climate=climate,
            pricing=pricing,
            carriers=self.catalog,
            dispatcher=self.dispatcher,
            clock=self.clock,
            sweep_age_seconds=SWEEP_AGE_SECONDS,
            retry_window_seconds=RETRY_WINDOW_SECONDS,
        )

    # Predictable identifiers, so a test can tell a second generated id from the stored one.

    def _next_submission(self) -> SubmissionId:
        self._submissions += 1
        return SubmissionId(f"S-{self._submissions:06d}")

    def _next_event(self) -> EventId:
        self._events += 1
        return EventId(f"0190a8e0-0000-7000-8000-{self._events:012d}")

    async def approvals_sweep(self) -> int:
        self.sweeps += 1
        if self.sweep_failure is not None:
            raise self.sweep_failure
        return 0

    # States a test starts from

    async def draft(self, principal: Principal = API_KEY, label: str | None = None) -> QuoteId:
        command = CreateQuote(
            location=QuoteLocationInput(lat=builders.LAT, lon=builders.LON, label=label),
            cover=builders.cover(),
            simulation=SimulationOptions(n=1_000),
        )
        view = await self.quoting.create_quote(principal, command, None, "api_client")
        return view.quote_id

    async def pending(
        self, principal: Principal = API_KEY, carrier_id: str = "carrier-1"
    ) -> Submission:
        quote_id = await self.draft(principal)
        return await self.approvals.request_submission(principal, quote_id, carrier_id, "agent")

    async def approved(self, principal: Principal = BROWSER) -> ApprovalView:
        submission = await self.pending(principal)
        return await self.approvals.decide(
            principal, submission.submission_id, Decision(approve=True)
        )

    async def abandoned(self, principal: Principal = BROWSER) -> ApprovalView:
        """An approved submission whose delivery was given up, as the deliver endpoint does."""
        approval = await self.approved(principal)
        at = self.clock.now()
        await self.quotes.update_for_event(
            self.record_of(approval.quote_id).event_id,
            lambda quote, record: quote.mark_abandoned(record, at=at),
        )
        return approval

    # What a test reads

    async def view(self, quote_id: QuoteId) -> QuoteView:
        quote = self.quotes.quotes[quote_id]
        return quote.view(await self.quotes.audit(quote_id))

    def delivery(self, quote_id: QuoteId) -> DeliveryState:
        submission = self.quotes.quotes[quote_id].submission
        assert submission is not None
        return submission.delivery

    def record_of(self, quote_id: QuoteId) -> OutboxRecord:
        (record,) = [r for r in self.outbox.records.values() if r.quote_id == quote_id]
        return record

    def audit_codes(self, quote_id: QuoteId) -> list[str]:
        return [entry.action.code for entry in self.quotes.trails[quote_id]]
