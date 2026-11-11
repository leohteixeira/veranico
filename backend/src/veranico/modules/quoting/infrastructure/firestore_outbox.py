"""`quoting_outbox/{event_id}`: the `SubmissionApproved` event and its delivery bookkeeping.

The records are created and changed together with their quote by `FirestoreQuoteRepository`;
this store reads them and moves a `pending` record to `enqueued`. The status query filters
on one equality field, so it needs no composite index.
"""

from datetime import datetime

from google.cloud.firestore import AsyncClient, AsyncTransaction
from google.cloud.firestore_v1.base_query import FieldFilter

from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus
from veranico.modules.quoting.infrastructure.mapping import OUTBOX, outbox_from_document
from veranico.modules.quoting.infrastructure.transactions import run_in_transaction
from veranico.shared.kernel.ids import EventId


class FirestoreOutboxStore:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._collection = client.collection(OUTBOX)

    async def get(self, event_id: EventId) -> OutboxRecord | None:
        document = (await self._collection.document(event_id).get()).to_dict()
        return outbox_from_document(document) if document is not None else None

    async def list_by_status(self, status: OutboxStatus) -> list[OutboxRecord]:
        query = self._collection.where(filter=FieldFilter("status", "==", status))
        records = []
        async for snapshot in query.stream():
            document = snapshot.to_dict()
            if document is not None:
                records.append(outbox_from_document(document))
        return records

    async def mark_enqueued(self, event_id: EventId, at: datetime) -> None:
        reference = self._collection.document(event_id)

        async def body(transaction: AsyncTransaction) -> None:
            document = (await reference.get(transaction=transaction)).to_dict()
            if document is None:
                return
            record = outbox_from_document(document)
            enqueued = record.mark_enqueued(at)
            if enqueued is not record:
                transaction.update(
                    reference, {"status": enqueued.status, "enqueued_at": enqueued.enqueued_at}
                )

        await run_in_transaction(self._client, body)
