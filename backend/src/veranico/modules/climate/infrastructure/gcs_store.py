"""`WeatherStore` on Cloud Storage, the store of the deployed service.

Manifests and aliases are objects read and written through the shared `BlobStore`. A
manifest is switched by an upload with a generation precondition: creating it requires that
no manifest exists, replacing it requires the generation that was read. Cloud Storage
applies the precondition atomically, so of two writers, in any number of processes, one
wins.

Zarr builds go through `zarr.storage.FsspecStore` over gcsfs, under the same bucket and
the same paths. Checked against zarr 3.4.2 and gcsfs 2026.7.0:

* `FsspecStore` needs an asynchronous filesystem.
* `gcsfs.GCSFileSystem`, and so `FsspecStore.from_url("gs://...")`, is by default the
  extended filesystem, which asks the bucket's type over gRPC before the first operation.
  Against the emulator that call waits a minute and fails. `gcsfs.core.GCSFileSystem` is
  the plain JSON API client; the bucket here is an ordinary one, so that class is used.
* gcsfs has no automatic anonymous mode: against the emulator the token is `anon` and the
  endpoint is passed explicitly. Otherwise it uses Application Default Credentials.
"""

from gcsfs.core import GCSFileSystem
from zarr.storage import FsspecStore

from veranico.modules.climate.infrastructure.manifest_store import Document, ManifestWeatherStore
from veranico.shared.infrastructure.blobs import (
    BlobNotFoundError,
    BlobPreconditionError,
    BlobStore,
)
from veranico.shared.kernel.clock import Clock

JSON = "application/json"
MUST_NOT_EXIST = 0  # the generation precondition that means "create only"


class GcsStorage:
    def __init__(
        self, blobs: BlobStore, bucket: str, emulator_host: str | None, prefix: str = ""
    ) -> None:
        self._blobs = blobs
        self._bucket = bucket
        self._emulator_host = emulator_host
        self._prefix = prefix

    async def read(self, path: str) -> Document | None:
        try:
            blob = await self._blobs.get(self._prefix + path)
        except BlobNotFoundError:
            return None
        return Document(text=blob.data.decode("utf-8"), version=blob.generation)

    async def switch(self, path: str, text: str, expected: Document | None) -> bool:
        generation = MUST_NOT_EXIST if expected is None else expected.version
        try:
            await self._blobs.put(
                self._prefix + path,
                text.encode("utf-8"),
                content_type=JSON,
                if_generation_match=generation,
            )
        except BlobPreconditionError:
            return False
        return True

    async def put(self, path: str, text: str) -> None:
        await self._blobs.put(self._prefix + path, text.encode("utf-8"), content_type=JSON)

    async def exists(self, path: str) -> bool:
        return await self._blobs.exists(self._prefix + path)

    def zarr(self, build_path: str, *, read_only: bool) -> FsspecStore:
        if self._emulator_host is not None:
            filesystem = GCSFileSystem(
                token="anon",
                endpoint_url=self._emulator_host,
                asynchronous=True,
            )
        else:
            filesystem = GCSFileSystem(asynchronous=True)
        return FsspecStore(
            filesystem, path=f"{self._bucket}/{self._prefix}{build_path}", read_only=read_only
        )

    async def remove_build(self, build_path: str) -> None:
        for name in await self._blobs.list(f"{self._prefix}{build_path}/"):
            await self._blobs.delete(name)


class GcsWeatherStore(ManifestWeatherStore):
    """`prefix` puts the whole layout under a folder of the bucket; the service uses none."""

    def __init__(
        self,
        blobs: BlobStore,
        bucket: str,
        emulator_host: str | None,
        clock: Clock,
        *,
        prefix: str = "",
    ) -> None:
        super().__init__(GcsStorage(blobs, bucket, emulator_host, prefix), clock)
