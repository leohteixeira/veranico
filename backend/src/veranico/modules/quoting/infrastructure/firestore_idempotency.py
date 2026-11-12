"""`quoting_idempotency/{ref}`: `workspace_id`, `fingerprint`, `quote_id`, `expires_at`.

`ref` is the SHA-256 of the workspace id and the key, so the document id says nothing
about either. The reservation is one atomic `create`: of many concurrent requests with one
key exactly one creates the document, and the others read what it stored.
"""

from datetime import datetime, timedelta

from google.api_core.exceptions import Conflict
from google.cloud.firestore import AsyncClient

from veranico.modules.quoting.application.ports import Reservation
from veranico.modules.quoting.infrastructure.mapping import IDEMPOTENCY
from veranico.shared.kernel.errors import ConflictError
from veranico.shared.kernel.ids import QuoteId, WorkspaceId


class FirestoreIdempotencyStore:
    def __init__(self, client: AsyncClient, *, ttl: timedelta) -> None:
        self._collection = client.collection(IDEMPOTENCY)
        self._ttl = ttl

    async def reserve(self, ref: str, wanted: Reservation, *, at: datetime) -> Reservation:
        reference = self._collection.document(ref)
        try:
            await reference.create(
                {
                    "workspace_id": wanted.workspace_id,
                    "fingerprint": wanted.fingerprint,
                    "quote_id": wanted.quote_id,
                    "expires_at": at + self._ttl,
                }
            )
        except Conflict:  # ALREADY_EXISTS: the key is reserved
            stored = (await reference.get()).to_dict()
            if stored is None:
                # Deleted by the TTL between the two calls: the caller may simply repeat.
                raise ConflictError("the idempotency key expired during the request") from None
            return Reservation(
                workspace_id=WorkspaceId(stored["workspace_id"]),
                fingerprint=stored["fingerprint"],
                quote_id=QuoteId(stored["quote_id"]),
            )
        return wanted
