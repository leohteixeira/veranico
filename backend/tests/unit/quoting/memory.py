"""In-memory stores for the ports of `quoting`, for unit tests.

They keep the atomicity of the real adapters: `create` fails when the id is taken, and
`update` writes the whole mutation or, when `mutate` raises, nothing. The dictionaries are
public, so a test can read what was stored.
"""

from collections.abc import Callable
from datetime import datetime

from veranico.modules.quoting.application.ports import QuoteAlreadyExistsError, Reservation
from veranico.modules.quoting.contracts import AuditEntry
from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId


class MemoryOutboxStore:
    def __init__(self) -> None:
        self.records: dict[EventId, OutboxRecord] = {}

    async def get(self, event_id: EventId) -> OutboxRecord | None:
        return self.records.get(event_id)

    async def list_by_status(self, status: OutboxStatus) -> list[OutboxRecord]:
        return [record for record in self.records.values() if record.status == status]

    async def mark_enqueued(self, event_id: EventId, at: datetime) -> None:
        record = self.records.get(event_id)
        if record is not None:
            self.records[event_id] = record.mark_enqueued(at)

    async def record_dispatch(self, event_id: EventId, next_attempt_at: datetime) -> None:
        record = self.records.get(event_id)
        if record is not None and not record.terminal:
            self.records[event_id] = record.after_dispatch(next_attempt_at)


class MemoryQuoteRepository:
    def __init__(self, outbox: MemoryOutboxStore | None = None) -> None:
        self.outbox = outbox or MemoryOutboxStore()
        self.quotes: dict[QuoteId, Quote] = {}
        self.trails: dict[QuoteId, list[AuditEntry]] = {}

    async def create(self, mutation: Mutation) -> None:
        if mutation.quote.quote_id in self.quotes:
            raise QuoteAlreadyExistsError
        self._write(mutation)

    async def get(self, quote_id: QuoteId) -> Quote | None:
        return self.quotes.get(quote_id)

    async def audit(self, quote_id: QuoteId) -> list[AuditEntry]:
        # A stable sort by time keeps the order of the entries of one mutation.
        return sorted(self.trails.get(quote_id, []), key=lambda entry: entry.at)

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> list[Quote]:
        return [quote for quote in self.quotes.values() if quote.workspace_id == workspace_id]

    async def find_by_submission(self, submission_id: SubmissionId) -> Quote | None:
        for quote in self.quotes.values():
            if quote.submission is not None and quote.submission.submission_id == submission_id:
                return quote
        return None

    async def update(self, quote_id: QuoteId, mutate: Callable[[Quote], Mutation]) -> Mutation:
        quote = self.quotes.get(quote_id)
        if quote is None:
            raise NotFoundError
        mutation = mutate(quote)
        self._write(mutation)
        return mutation

    async def update_for_event(
        self, event_id: EventId, mutate: Callable[[Quote, OutboxRecord], Mutation]
    ) -> Mutation:
        record = self.outbox.records.get(event_id)
        if record is None:
            raise NotFoundError
        mutation = mutate(self.quotes[record.quote_id], record)
        self._write(mutation)
        return mutation

    def _write(self, mutation: Mutation) -> None:
        quote = mutation.quote
        self.quotes[quote.quote_id] = quote
        self.trails.setdefault(quote.quote_id, []).extend(mutation.audit)
        for record in mutation.outbox:
            self.outbox.records[record.event_id] = record


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.reservations: dict[str, Reservation] = {}
        self.reserved_at: dict[str, datetime] = {}

    async def reserve(self, ref: str, wanted: Reservation, *, at: datetime) -> Reservation:
        if ref not in self.reservations:
            self.reservations[ref] = wanted
            self.reserved_at[ref] = at
        return self.reservations[ref]
