"""The mock carrier (`APP_ROLE=carrier`): verify a webhook, deduplicate it by event id and
answer with a receipt.

State of one event, in one document of `carriers_receipts`, moves forward only:
absent -> deferred (only when the "fail first attempt" switch is on) -> received.
Every step is a conditional write (create-if-absent, or an update that requires the
document unchanged since it was read), so concurrent duplicates of one event end with one
receipt and nobody holds a lock: a request that loses a write reads again and follows the
winner.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from veranico.modules.carriers.contracts import Receipt, WebhookEnvelope
from veranico.modules.carriers.domain.signing import Verification, verify
from veranico.shared.kernel import ids
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import DomainError, InvalidArgumentsError
from veranico.shared.kernel.ids import EventId

_logger = logging.getLogger(__name__)

# Contracts section 9: a receipt expires 14 days after it was received. A deferred marker
# carries the same field counted from when it was written, so no document is kept forever.
RECEIPT_TTL = timedelta(days=14)
# The event id becomes a document id; this accepts a UUID and nothing a path could abuse.
_EVENT_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
# absent -> deferred -> received: a request that loses a write needs at most three reads.
_MAX_ROUNDS = 3


# The answers of the mock carrier that contracts section 6 fixes by status. The API role
# reads only the status; these codes exist on the carrier's own wire and nowhere else.
class InvalidSignatureError(DomainError):
    code = "invalid_signature"
    status = 401


class StaleTimestampError(DomainError):
    code = "stale_timestamp"
    status = 400


class CarrierUnavailableError(DomainError):
    code = "carrier_unavailable"
    status = 503
    retryable = True


@dataclass(frozen=True, slots=True)
class StoredSubmission:
    receipt: Receipt | None  # None: the event was deferred and has no receipt yet
    version: object  # opaque token of the document as read, for `ReceiptStore.promote`


class ReceiptStore(Protocol):
    async def get(self, event_id: EventId) -> StoredSubmission | None: ...

    async def create_deferred(self, event_id: EventId, at: datetime, expires_at: datetime) -> bool:
        """Store the marker of a deferred event. False when a document already exists."""
        ...

    async def create_receipt(self, receipt: Receipt, expires_at: datetime) -> bool:
        """Store the receipt of a new event. False when a document already exists."""
        ...

    async def promote(
        self, deferred: StoredSubmission, receipt: Receipt, expires_at: datetime
    ) -> bool:
        """Turn the deferred marker into `receipt`. False when the document has changed
        since `deferred` was read."""
        ...


class Receiver:
    def __init__(
        self,
        *,
        store: ReceiptStore,
        clock: Clock,
        signing_secret: str,
        tolerance_seconds: int,
        fail_first_attempt: bool,
        new_receipt_id: Callable[[], str] = ids.new_receipt_id,
    ) -> None:
        self._store = store
        self._clock = clock
        self._signing_secret = signing_secret
        self._tolerance_seconds = tolerance_seconds
        self._fail_first_attempt = fail_first_attempt
        self._new_receipt_id = new_receipt_id

    def authenticate(
        self, timestamp_header: str | None, signature_header: str | None, body: bytes
    ) -> None:
        """Check the signature over the raw received bytes, before anything parses them."""
        outcome = verify(
            self._signing_secret,
            timestamp_header,
            signature_header,
            body,
            self._clock.now(),
            self._tolerance_seconds,
        )
        if outcome is Verification.BAD_SIGNATURE:
            raise InvalidSignatureError
        if outcome is Verification.STALE:
            raise StaleTimestampError

    async def receive(self, envelope: WebhookEnvelope) -> Receipt:
        """Return the receipt of the event: a new one, or the original for a replay.

        Raises `CarrierUnavailableError` for the first attempt of an event when the switch
        is on. Call only after `authenticate` accepted the request.
        """
        event_id = envelope.event_id
        if not _EVENT_ID.fullmatch(event_id):
            raise InvalidArgumentsError("event_id: not a valid identifier")
        now = self._clock.now()
        expires_at = now + RECEIPT_TTL
        for _ in range(_MAX_ROUNDS):
            stored = await self._store.get(event_id)
            if stored is not None and stored.receipt is not None:
                _logger.info("submission replayed", extra={"event_id": event_id})
                return stored.receipt
            if stored is None and self._fail_first_attempt:
                if await self._store.create_deferred(event_id, now, expires_at):
                    _logger.info("submission deferred", extra={"event_id": event_id})
                    raise CarrierUnavailableError
                continue
            receipt = Receipt(receipt_id=self._new_receipt_id(), event_id=event_id, received_at=now)
            written = (
                await self._store.create_receipt(receipt, expires_at)
                if stored is None
                else await self._store.promote(stored, receipt, expires_at)
            )
            if written:
                _logger.info(
                    "submission received",
                    extra={"event_id": event_id, "receipt_id": receipt.receipt_id},
                )
                return receipt
        # Unreachable while the state only moves forward; never answer with a guess.
        raise CarrierUnavailableError
