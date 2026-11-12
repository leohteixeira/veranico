"""`quoting_quotes/{quote_id}` with the append-only subcollection `audit`.

A mutation is written as a unit: the quote, its new audit entries and its outbox records
(`quoting_outbox/{event_id}`) in one batch (`create`) or one transaction (`update`).
Every document carries `expires_at`: the quote's creation time plus the workspace TTL.

Queries filter on one equality field and sort in code, so none needs a composite index.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from google.api_core.exceptions import Conflict
from google.cloud.firestore import AsyncClient, AsyncTransaction, AsyncWriteBatch
from google.cloud.firestore_v1.base_query import FieldFilter

from veranico.modules.quoting.application.ports import QuoteAlreadyExistsError
from veranico.modules.quoting.contracts import AuditEntry
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.modules.quoting.infrastructure.mapping import (
    AUDIT,
    OUTBOX,
    QUOTES,
    audit_document,
    audit_from_document,
    outbox_document,
    outbox_from_document,
    quote_document,
    quote_from_document,
)
from veranico.modules.quoting.infrastructure.transactions import run_in_transaction
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId


class FirestoreQuoteRepository:
    def __init__(self, client: AsyncClient, *, ttl: timedelta) -> None:
        self._client = client
        self._quotes = client.collection(QUOTES)
        self._outbox = client.collection(OUTBOX)
        self._ttl = ttl

    async def create(self, mutation: Mutation) -> None:
        batch = self._client.batch()
        self._write(batch, mutation, new=True)
        try:
            await batch.commit()
        except Conflict as error:  # ALREADY_EXISTS: the batch wrote nothing
            raise QuoteAlreadyExistsError from error

    async def get(self, quote_id: QuoteId) -> Quote | None:
        document = (await self._quotes.document(quote_id).get()).to_dict()
        return quote_from_document(document) if document is not None else None

    async def audit(self, quote_id: QuoteId) -> list[AuditEntry]:
        """Oldest first by the entry's time; entries of one instant by commit, then `seq`."""
        rows: list[tuple[datetime, datetime, int, AuditEntry]] = []
        async for snapshot in self._quotes.document(quote_id).collection(AUDIT).stream():
            document = snapshot.to_dict()
            if document is None:
                continue
            entry = audit_from_document(document)
            rows.append((entry.at, snapshot.create_time, document["seq"], entry))
        rows.sort(key=lambda row: row[:3])
        return [row[3] for row in rows]

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> list[Quote]:
        return await self._where("workspace_id", workspace_id)

    async def find_by_submission(self, submission_id: SubmissionId) -> Quote | None:
        found = await self._where("submission_id", submission_id)
        return found[0] if found else None

    async def update(self, quote_id: QuoteId, mutate: Callable[[Quote], Mutation]) -> Mutation:
        async def body(transaction: AsyncTransaction) -> Mutation:
            quote = await self._read(transaction, quote_id)
            mutation = mutate(quote)
            self._write(transaction, mutation, before=quote)
            return mutation

        return await run_in_transaction(self._client, body)

    async def update_for_event(
        self, event_id: EventId, mutate: Callable[[Quote, OutboxRecord], Mutation]
    ) -> Mutation:
        async def body(transaction: AsyncTransaction) -> Mutation:
            snapshot = await self._outbox.document(event_id).get(transaction=transaction)
            document = snapshot.to_dict()
            if document is None:
                raise NotFoundError
            record = outbox_from_document(document)
            quote = await self._read(transaction, record.quote_id)
            mutation = mutate(quote, record)
            self._write(transaction, mutation, before=quote)
            return mutation

        return await run_in_transaction(self._client, body)

    async def _where(self, field: str, value: str) -> list[Quote]:
        query = self._quotes.where(filter=FieldFilter(field, "==", value))
        quotes = []
        async for snapshot in query.stream():
            document = snapshot.to_dict()
            if document is not None:
                quotes.append(quote_from_document(document))
        return quotes

    async def _read(self, transaction: AsyncTransaction, quote_id: QuoteId) -> Quote:
        snapshot = await self._quotes.document(quote_id).get(transaction=transaction)
        document = snapshot.to_dict()
        if document is None:
            raise NotFoundError
        return quote_from_document(document)

    def _write(
        self,
        writer: AsyncWriteBatch,
        mutation: Mutation,
        *,
        before: Quote | None = None,
        new: bool = False,
    ) -> None:
        """Queue the writes of one mutation; a mutation that changes nothing writes nothing."""
        quote = mutation.quote
        expires_at = quote.created_at + self._ttl
        reference = self._quotes.document(quote.quote_id)
        if new:
            writer.create(reference, quote_document(quote, expires_at))
        elif quote != before:
            writer.set(reference, quote_document(quote, expires_at))
        for seq, entry in enumerate(mutation.audit):
            # A fresh auto id on every run: an earlier run of a retried transaction wrote nothing.
            writer.create(
                reference.collection(AUDIT).document(), audit_document(entry, seq, expires_at)
            )
        for record in mutation.outbox:
            writer.set(self._outbox.document(record.event_id), outbox_document(record, expires_at))
