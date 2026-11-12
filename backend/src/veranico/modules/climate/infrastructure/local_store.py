"""`WeatherStore` on the local filesystem, for development and tests.

A manifest is switched by writing a temporary file and renaming it over the old one. A
lock makes "is the manifest still the one that was read? then replace it" one step, so of
two writers in this process one wins. Like `LocalBlobStore`, the store is not meant for
more than one process.
"""

import asyncio
import os
import shutil
import threading
from pathlib import Path

from veranico.modules.climate.infrastructure.manifest_store import Document, ManifestWeatherStore
from veranico.shared.kernel.clock import Clock


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._switch_lock = threading.Lock()

    async def read(self, path: str) -> Document | None:
        return await asyncio.to_thread(self._read, path)

    async def switch(self, path: str, text: str, expected: Document | None) -> bool:
        return await asyncio.to_thread(self._switch, path, text, expected)

    async def put(self, path: str, text: str) -> None:
        await asyncio.to_thread(_replace, self._root / path, text)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread((self._root / path).exists)

    def zarr(self, build_path: str, *, read_only: bool) -> Path:
        target = self._root / build_path
        if not read_only:
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def remove_build(self, build_path: str) -> None:
        await asyncio.to_thread(shutil.rmtree, self._root / build_path, ignore_errors=True)

    def _read(self, path: str) -> Document | None:
        try:
            return Document(text=(self._root / path).read_text(encoding="utf-8"), version=None)
        except FileNotFoundError:
            return None

    def _switch(self, path: str, text: str, expected: Document | None) -> bool:
        with self._switch_lock:
            if self._read(path) != expected:
                return False
            _replace(self._root / path, text)
            return True


class LocalWeatherStore(ManifestWeatherStore):
    def __init__(self, root: Path, clock: Clock) -> None:
        super().__init__(LocalStorage(root), clock)


def _replace(target: Path, text: str) -> None:
    """Write to a temporary file in the same directory, then rename over the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
