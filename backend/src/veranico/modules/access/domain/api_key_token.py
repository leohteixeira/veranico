"""The API key bearer: `vrk_<key_id>_<secret>`.

`key_id` is public and names the stored document; the secret is 256 random bits and is
stored only as its SHA-256. A fast hash is right here because the secret is random and
long, not a password.
"""

import hashlib
import hmac
import re
import secrets

_PREFIX = "vrk"
_KEY_ID = re.compile(r"[0-9a-f]{1,64}")


def mint() -> tuple[str, str]:
    """Return a new `(key_id, secret)`. The key id is hexadecimal, so it has no underscore."""
    return secrets.token_hex(8), secrets.token_urlsafe(32)


def format_bearer(key_id: str, secret: str) -> str:
    return f"{_PREFIX}_{key_id}_{secret}"


def parse_bearer(bearer: str) -> tuple[str, str] | None:
    """Return `(key_id, secret)`, or `None` for anything that is not a bearer of this form."""
    parts = bearer.split("_", 2)  # the secret may itself contain underscores
    if len(parts) != 3 or parts[0] != _PREFIX or not parts[2]:
        return None
    # The key id names a stored document, so only the form `mint` writes is looked up.
    if _KEY_ID.fullmatch(parts[1]) is None:
        return None
    return parts[1], parts[2]


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def secret_matches(secret: str, secret_hash: str) -> bool:
    """Constant-time comparison of a presented secret with a stored hash."""
    return hmac.compare_digest(hash_secret(secret).encode(), secret_hash.encode())
