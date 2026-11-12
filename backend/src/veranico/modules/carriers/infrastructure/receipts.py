"""`carriers_receipts` in Firestore: the state of the mock carrier (carrier role only).

One document per event id. `status` is `deferred` or `received`; every document carries
`expires_at` as a Firestore timestamp, the type the TTL policy needs (a field of another
type disables TTL for that document). TTL deletion is not immediate, so an expired document
can still be read; answering a replay with its original receipt stays correct.

No transaction is used: each write is conditional (create-if-absent, or an update with the
`last_update_time` precondition), so the code holds no lock across a read and a write.

A write that loses to a concurrent one answers `AlreadyExists` (create) or
`FailedPrecondition` (update). Under contention on one document the server can instead
answer `Aborted` (the Firestore emulator does, as "Transaction lock timeout"). An aborted
write was not applied, so all three mean the same here: not written, read again.
"""

from datetime import datetime
from typing import Any

from google.api_core.exceptions import Aborted, AlreadyExists, FailedPrecondition
from google.cloud.firestore import AsyncClient, AsyncDocumentReference

from veranico.modules.carriers.application.receive import StoredSubmission
from veranico.modules.carriers.contracts import Receipt
from veranico.shared.kernel.ids import EventId

COLLECTION = "carriers_receipts"
_DEFERRED = "deferred"
_RECEIVED = "received"


class FirestoreReceiptStore:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def get(self, event_id: EventId) -> StoredSubmission | None:
        snapshot = await self._document(event_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("status") != _RECEIVED:
            return StoredSubmission(receipt=None, version=snapshot.update_time)
        receipt = Receipt(
            receipt_id=data["receipt_id"], event_id=event_id, received_at=data["received_at"]
        )
        return StoredSubmission(receipt=receipt, version=snapshot.update_time)

    async def create_deferred(self, event_id: EventId, at: datetime, expires_at: datetime) -> bool:
        return await self._create(
            event_id,
            {
                "status": _DEFERRED,
                "event_id": event_id,
                "deferred_at": at,
                "expires_at": expires_at,
            },
        )

    async def create_receipt(self, receipt: Receipt, expires_at: datetime) -> bool:
        return await self._create(
            receipt.event_id, {"event_id": receipt.event_id, **_received(receipt, expires_at)}
        )

    async def promote(
        self, deferred: StoredSubmission, receipt: Receipt, expires_at: datetime
    ) -> bool:
        unchanged = self._client.write_option(last_update_time=deferred.version)
        try:
            await self._document(receipt.event_id).update(
                _received(receipt, expires_at), option=unchanged
            )
        except (FailedPrecondition, Aborted):
            return False
        return True

    async def _create(self, event_id: EventId, data: dict[str, Any]) -> bool:
        try:
            await self._document(event_id).create(data)
        except (AlreadyExists, Aborted):
            return False
        return True

    def _document(self, event_id: EventId) -> AsyncDocumentReference:
        return self._client.collection(COLLECTION).document(event_id)


def _received(receipt: Receipt, expires_at: datetime) -> dict[str, Any]:
    return {
        "status": _RECEIVED,
        "receipt_id": receipt.receipt_id,
        "received_at": receipt.received_at,
        "expires_at": expires_at,
    }
