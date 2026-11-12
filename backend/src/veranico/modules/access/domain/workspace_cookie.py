"""The value of the workspace cookie: `v1.<workspace_id>.<expires_unix>.<hex>`.

The last part is the HMAC SHA-256 of the first three under the cookie signing secret, so
neither the workspace id nor the expiry can be edited. A value that does not verify is
treated by the caller as no cookie at all: there is no access gate, a new workspace opens.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from veranico.shared.kernel.ids import WorkspaceId

_VERSION = "v1"


def new_workspace_id() -> WorkspaceId:
    """128 random bits in hexadecimal."""
    return WorkspaceId(secrets.token_hex(16))


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign(workspace_id: WorkspaceId, expires_at: datetime, secret: str) -> str:
    payload = f"{_VERSION}.{workspace_id}.{int(expires_at.timestamp())}"
    return f"{payload}.{_signature(payload, secret)}"


def verify(value: str, secret: str, now: datetime) -> tuple[WorkspaceId, datetime] | None:
    """Return the workspace id and expiry of a valid, unexpired value, else `None`."""
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != _VERSION:
        return None
    version, workspace_id, expires, signature = parts
    expected = _signature(f"{version}.{workspace_id}.{expires}", secret)
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        return None
    # The signature covers the expiry, so from here on it is the text this service wrote.
    expires_at = datetime.fromtimestamp(int(expires), UTC)
    if expires_at <= now:
        return None
    return WorkspaceId(workspace_id), expires_at
