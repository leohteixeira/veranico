"""Blob storage port shared by the modules that keep objects (`climate`, `documents`).

Paths are relative to the store root and start with the owning module's prefix
(`climate/...`, `documents/...`). A generation is the store's version number of an object:
it changes on every write, and a write can be made conditional on it.
"""

import asyncio
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud.storage import Client as StorageClient

from veranico.shared.infrastructure.settings import Settings

# The port has a method named `list`, which hides the builtin inside the class bodies.
Paths = list[str]


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

    async def list(self, prefix: str) -> Paths:
        """Return the paths that start with `prefix`, sorted."""
        ...


class LocalBlobStore:
    """Objects as files under a root directory, for development and tests.

    The bytes of `<path>` live in `<root>/<path>` and its generation, a counter, in
    `<root>/.generations/<path>`. Both are replaced atomically (temporary file, then rename),
    and a lock makes the precondition check and the write one step inside this process.
    A crash between the two renames leaves the generation one write behind; the store is
    not meant for more than one process.
    """

    _GENERATIONS = ".generations"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()

    async def get(self, path: str) -> Blob:
        return await asyncio.to_thread(self._locked, lambda: self._get(path))

    async def put(
        self,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        if_generation_match: int | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._locked, lambda: self._put(path, data, if_generation_match)
        )

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._locked, lambda: self._file(path).is_file())

    async def delete(self, path: str) -> None:
        await asyncio.to_thread(self._locked, lambda: self._delete(path))

    async def list(self, prefix: str) -> Paths:
        return await asyncio.to_thread(self._locked, lambda: self._list(prefix))

    def _locked[T](self, operation: Callable[[], T]) -> T:
        with self._lock:
            return operation()

    def _file(self, path: str) -> Path:
        return self._root / _relative(path)

    def _generation_file(self, path: str) -> Path:
        return self._root / self._GENERATIONS / _relative(path)

    def _generation(self, path: str) -> int:
        if not self._file(path).is_file():
            return 0
        return int(self._generation_file(path).read_text(encoding="ascii"))

    def _get(self, path: str) -> Blob:
        try:
            data = self._file(path).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise BlobNotFoundError(path) from None
        return Blob(data=data, generation=self._generation(path))

    def _put(self, path: str, data: bytes, if_generation_match: int | None) -> int:
        current = self._generation(path)
        if if_generation_match is not None and if_generation_match != current:
            raise BlobPreconditionError(
                f"{path}: expected generation {if_generation_match}, found {current}"
            )
        generation = current + 1
        _replace(self._file(path), data)
        _replace(self._generation_file(path), str(generation).encode("ascii"))
        return generation

    def _delete(self, path: str) -> None:
        self._file(path).unlink(missing_ok=True)
        self._generation_file(path).unlink(missing_ok=True)

    def _list(self, prefix: str) -> Paths:
        if not self._root.is_dir():
            return []
        names = (
            file.relative_to(self._root).as_posix()
            for file in self._root.rglob("*")
            if file.is_file() and not file.name.endswith(_TEMPORARY_SUFFIX)
        )
        return sorted(
            name
            for name in names
            if name.startswith(prefix) and not name.startswith(f"{self._GENERATIONS}/")
        )


class GcsBlobStore:
    """Objects in one Cloud Storage bucket. The client is synchronous, so calls run in threads."""

    def __init__(self, client: StorageClient, bucket: str) -> None:
        self._client = client
        self._bucket = client.bucket(bucket)

    async def get(self, path: str) -> Blob:
        return await asyncio.to_thread(self._get, path)

    async def put(
        self,
        path: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        if_generation_match: int | None = None,
    ) -> int:
        return await asyncio.to_thread(self._put, path, data, content_type, if_generation_match)

    async def exists(self, path: str) -> bool:
        return bool(await asyncio.to_thread(self._bucket.blob(path).exists))

    async def delete(self, path: str) -> None:
        await asyncio.to_thread(self._delete, path)

    async def list(self, prefix: str) -> Paths:
        return await asyncio.to_thread(self._list, prefix)

    def _get(self, path: str) -> Blob:
        blob = self._bucket.blob(path)
        try:
            data = blob.download_as_bytes()
        except NotFound:
            raise BlobNotFoundError(path) from None
        return Blob(data=data, generation=int(blob.generation))

    def _put(
        self, path: str, data: bytes, content_type: str, if_generation_match: int | None
    ) -> int:
        blob = self._bucket.blob(path)
        try:
            blob.upload_from_string(
                data, content_type=content_type, if_generation_match=if_generation_match
            )
        except PreconditionFailed:
            raise BlobPreconditionError(
                f"{path}: generation {if_generation_match} is not the current one"
            ) from None
        return int(blob.generation)

    def _delete(self, path: str) -> None:
        try:
            self._bucket.blob(path).delete()
        except NotFound:
            return

    def _list(self, prefix: str) -> Paths:
        return sorted(blob.name for blob in self._client.list_blobs(self._bucket, prefix=prefix))


def storage_client(settings: Settings) -> StorageClient:
    """Build the Cloud Storage client: anonymous against the emulator, otherwise with ADC."""
    if settings.storage_emulator_host is not None:
        return StorageClient(
            project=settings.firestore_project,
            client_options={"api_endpoint": settings.storage_emulator_host},
            use_auth_w_custom_endpoint=False,  # anonymous credentials
        )
    return StorageClient(project=settings.firestore_project)


def blob_store(settings: Settings) -> BlobStore:
    """Build the store the blob backend setting names."""
    if settings.blob_backend == "gcs":
        return GcsBlobStore(storage_client(settings), settings.storage_bucket)
    return LocalBlobStore(settings.data_root / "blobs")


_TEMPORARY_SUFFIX = ".tmp"


def _relative(path: str) -> PurePosixPath:
    """Refuse a path that could leave the store root."""
    relative = PurePosixPath(path)
    if not path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid blob path: {path!r}")
    return relative


def _replace(target: Path, data: bytes) -> None:
    """Write to a temporary file in the same directory, then rename over the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}{_TEMPORARY_SUFFIX}")
    temporary.write_bytes(data)
    os.replace(temporary, target)
