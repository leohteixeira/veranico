"""Blob storage port shared by the modules that keep objects (`climate`, `documents`).

Paths are relative to the store root and start with the owning module's prefix
(`climate/...`, `documents/...`). A generation is the store's version number of an object:
it changes on every write, and a write can be made conditional on it.
"""

from dataclasses import dataclass
from typing import Protocol


class BlobNotFoundError(Exception):
    """The object does not exist."""


class BlobPreconditionError(Exception):
    """A conditional write found another generation than the one it expected."""


@dataclass(frozen=True, slots=True)
class Blob:
    data: bytes
    generation: int


class BlobStore(Protocol):
    async def get(self, path: str) -> Blob:
        """Return the bytes with the object's generation; raise `BlobNotFoundError`."""
        ...

    async def put(
        self,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        if_generation_match: int | None = None,
    ) -> int:
        """Replace the object atomically and return its new generation.

        With `if_generation_match` the write happens only when the object's current
        generation equals it; `0` means the object must not exist yet. Otherwise
        `BlobPreconditionError` is raised and nothing is written.
        """
        ...

    async def exists(self, path: str) -> bool: ...

    async def delete(self, path: str) -> None:
        """Delete the object; a missing object is not an error."""
        ...

    async def list(self, prefix: str) -> list[str]:
        """Return the paths that start with `prefix`, sorted."""
        ...
