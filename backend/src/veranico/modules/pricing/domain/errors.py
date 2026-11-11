"""The domain errors `pricing` raises (contracts section 4), named in one place.

They are the shared kernel's classes: the code and the HTTP status are fixed there.
"""

from veranico.shared.kernel.errors import InsufficientHistoryError, InvalidCoverError

__all__ = ["InsufficientHistoryError", "InvalidCoverError"]
