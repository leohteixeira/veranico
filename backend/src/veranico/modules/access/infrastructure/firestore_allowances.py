"""`access_allowances/{ip_hash}-{YYYYMMDD}`: `conversations_used`, `messages_used`,
`expires_at` (the TTL field).

The document is named by the visitor's salted hash and the UTC day. No address is stored.
"""

from datetime import datetime
from typing import Any

from google.api_core.exceptions import Conflict, FailedPrecondition, NotFound
from google.cloud.firestore import AsyncClient

from veranico.modules.access.domain.allowance import Limits, Usage, consume

COLLECTION = "access_allowances"


def _usage(data: dict[str, Any] | None) -> Usage:
    if data is None:
        return Usage()
    return Usage(conversations_used=data["conversations_used"], messages_used=data["messages_used"])


class FirestoreAllowanceStore:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._collection = client.collection(COLLECTION)

    async def usage(self, ip_hash: str, day: str) -> Usage:
        snapshot = await self._collection.document(f"{ip_hash}-{day}").get()
        return _usage(snapshot.to_dict())

    async def consume(
        self,
        ip_hash: str,
        day: str,
        *,
        limits: Limits,
        new_conversation: bool,
        expires_at: datetime,
    ) -> tuple[Usage, bool]:
        """Read, check both limits and write, the write conditional on what was read.

        A blind increment cannot enforce a limit, so the write carries a precondition:
        create only when the document was absent, otherwise update only when it is still
        the version that was read. The server applies check and write atomically. When
        another call got in between, the precondition fails, nothing is written, and the
        loop reads again. Every failed round means another call was counted, so the loop
        ends: either this write lands or the limits refuse it.

        A read-then-write transaction is not used: transactions lock what they read, and
        two of them racing on this one document block each other until the lock times out
        (measured on the emulator: two racing calls both failed after five attempts).
        """
        reference = self._collection.document(f"{ip_hash}-{day}")
        while True:
            snapshot = await reference.get()
            usage = _usage(snapshot.to_dict())
            updated = consume(limits, usage, new_conversation)
            if updated is None:
                return usage, False
            data = {
                "conversations_used": updated.conversations_used,
                "messages_used": updated.messages_used,
                "expires_at": expires_at,
            }
            try:
                if snapshot.exists:
                    await reference.update(
                        data,
                        option=self._client.write_option(last_update_time=snapshot.update_time),
                    )
                else:
                    await reference.create(data)
            except (Conflict, FailedPrecondition, NotFound):
                continue  # written, changed or deleted since the read: read again
            return updated, True
