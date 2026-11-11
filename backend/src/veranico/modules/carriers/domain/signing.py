"""Webhook signature: one pair of pure functions used by both roles, so the sender and the
mock carrier cannot drift.

Wire form (contracts section 6): `Veranico-Timestamp: <Unix seconds>` and
`Veranico-Signature: v1=<hex>`, where the hex is HMAC SHA-256 of the bytes
`"<timestamp>." + raw body` under the shared secret.
"""

import hashlib
import hmac
from datetime import datetime
from enum import Enum

TIMESTAMP_HEADER = "Veranico-Timestamp"
SIGNATURE_HEADER = "Veranico-Signature"
_VERSION_PREFIX = "v1="


class Verification(Enum):
    OK = "ok"
    BAD_SIGNATURE = "bad_signature"
    STALE = "stale"


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """The `Veranico-Signature` value for `body` sent at `timestamp` (Unix seconds).

    `body` must be the exact bytes that go on the wire.
    """
    return _signature(secret, str(timestamp), body)


def verify(
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    body: bytes,
    now: datetime,
    tolerance_seconds: int,
) -> Verification:
    """Check the two headers against the raw received `body`.

    The signature is checked first, so only a correctly signed request can be told that it
    is stale; anything unsigned, malformed or tampered is `BAD_SIGNATURE`. `now` is
    timezone-aware. A request is stale when it is more than `tolerance_seconds` old, counted
    in whole seconds.
    """
    if not timestamp_header or not signature_header:
        return Verification.BAD_SIGNATURE
    # ASCII digits only: `str.isdigit` alone also accepts other scripts' digits.
    if not (timestamp_header.isascii() and timestamp_header.isdigit()):
        return Verification.BAD_SIGNATURE
    # The MAC is recomputed over the header text as received and compared as bytes:
    # `hmac.compare_digest` is constant-time and, on bytes, accepts any header content.
    expected = _signature(secret, timestamp_header, body)
    if not hmac.compare_digest(expected.encode("ascii"), signature_header.encode("utf-8")):
        return Verification.BAD_SIGNATURE
    # Whole seconds on both sides: the header has that resolution, so a sub-second part of
    # `now` must not make a request at exactly the tolerance look older than it is.
    if int(now.timestamp()) - int(timestamp_header) > tolerance_seconds:
        return Verification.STALE
    return Verification.OK


def _signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return _VERSION_PREFIX + digest
