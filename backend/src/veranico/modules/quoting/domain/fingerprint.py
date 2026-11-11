"""The fingerprint that tells a replayed `CreateQuote` from a different one under the same key."""

import hashlib
import json

from veranico.modules.quoting.contracts import CreateQuote


def fingerprint(command: CreateQuote) -> str:
    """SHA-256 of the canonical JSON of the command as received, before any resolution.

    The model's own serialisation fills the defaults, so an explicit default equals an
    omitted one.
    """
    canonical = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
