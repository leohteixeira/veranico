import asyncio
from pathlib import Path

import pytest

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.blobs import (
    Blob,
    BlobNotFoundError,
    BlobPreconditionError,
    BlobStore,
    GcsBlobStore,
    LocalBlobStore,
    blob_store,
)


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def test_round_trip_returns_the_bytes_with_a_generation(store: LocalBlobStore) -> None:
    generation = await store.put("documents/ws-1/Q-1/term-sheet-en.pdf", b"%PDF-1")

    blob = await store.get("documents/ws-1/Q-1/term-sheet-en.pdf")

    assert blob == Blob(data=b"%PDF-1", generation=generation)
    assert generation > 0


async def test_a_missing_object_is_not_found_and_does_not_exist(store: LocalBlobStore) -> None:
    assert await store.exists("climate/points/x/manifest.json") is False
    with pytest.raises(BlobNotFoundError):
        await store.get("climate/points/x/manifest.json")


async def test_every_write_changes_the_generation(store: LocalBlobStore) -> None:
    first = await store.put("climate/a", b"1")
    second = await store.put("climate/a", b"2")

    assert second != first
    assert await store.get("climate/a") == Blob(data=b"2", generation=second)


async def test_conditional_write_succeeds_with_the_current_generation(
    store: LocalBlobStore,
) -> None:
    first = await store.put("climate/a", b"1")

    second = await store.put("climate/a", b"2", if_generation_match=first)

    assert (await store.get("climate/a")).data == b"2"
    assert second != first


async def test_stale_precondition_fails_and_writes_nothing(store: LocalBlobStore) -> None:
    first = await store.put("climate/a", b"1")
    second = await store.put("climate/a", b"2")

    with pytest.raises(BlobPreconditionError):
        await store.put("climate/a", b"3", if_generation_match=first)

    assert await store.get("climate/a") == Blob(data=b"2", generation=second)


async def test_generation_zero_means_create_only(store: LocalBlobStore) -> None:
    await store.put("climate/a", b"1", if_generation_match=0)

    with pytest.raises(BlobPreconditionError):
        await store.put("climate/a", b"2", if_generation_match=0)

    assert (await store.get("climate/a")).data == b"1"


async def test_precondition_on_a_missing_object_fails(store: LocalBlobStore) -> None:
    with pytest.raises(BlobPreconditionError):
        await store.put("climate/a", b"1", if_generation_match=7)

    assert await store.exists("climate/a") is False


async def test_only_one_of_many_concurrent_create_only_writes_wins(store: LocalBlobStore) -> None:
    async def create(number: int) -> bool:
        try:
            await store.put("climate/alias.json", str(number).encode(), if_generation_match=0)
        except BlobPreconditionError:
            return False
        return True

    results = await asyncio.gather(*(create(number) for number in range(20)))

    assert results.count(True) == 1


async def test_replace_is_atomic_and_leaves_no_temporary_file(
    store: LocalBlobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await store.put("climate/a", b"old")

    def fail(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(OSError, match="disk full"):
        await store.put("climate/a", b"new and longer")
    monkeypatch.undo()

    assert (await store.get("climate/a")).data == b"old"
    assert await store.list("") == ["climate/a"]
    await store.put("climate/a", b"new")
    names = sorted(path.name for path in (tmp_path / "blobs" / "climate").iterdir())
    assert [name for name in names if not name.endswith(".tmp")] == ["a"]


async def test_delete_removes_the_object_and_tolerates_a_missing_one(store: LocalBlobStore) -> None:
    await store.put("climate/a", b"1")

    await store.delete("climate/a")
    await store.delete("climate/a")

    assert await store.exists("climate/a") is False
    assert await store.put("climate/a", b"2", if_generation_match=0) > 0


async def test_list_returns_sorted_paths_under_a_prefix(store: LocalBlobStore) -> None:
    for path in ("documents/ws-1/Q-2/b.pdf", "documents/ws-1/Q-1/a.pdf", "climate/cubes/x"):
        await store.put(path, b"x")

    assert await store.list("documents/ws-1/") == [
        "documents/ws-1/Q-1/a.pdf",
        "documents/ws-1/Q-2/b.pdf",
    ]
    assert await store.list("") == [
        "climate/cubes/x",
        "documents/ws-1/Q-1/a.pdf",
        "documents/ws-1/Q-2/b.pdf",
    ]
    assert await store.list("nothing/") == []


async def test_list_on_an_empty_store_is_empty(store: LocalBlobStore) -> None:
    assert await store.list("") == []


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../outside", "climate/../../outside"])
async def test_a_path_that_could_leave_the_root_is_refused(
    store: LocalBlobStore, path: str
) -> None:
    with pytest.raises(ValueError, match="invalid blob path"):
        await store.put(path, b"x")
    with pytest.raises(ValueError, match="invalid blob path"):
        await store.get(path)


def test_factory_builds_the_backend_the_setting_names(tmp_path: Path) -> None:
    local: BlobStore = blob_store(settings_for_tests(data_root=tmp_path))
    remote: BlobStore = blob_store(
        settings_for_tests(blob_backend="gcs", storage_emulator_host="http://127.0.0.1:8590")
    )

    assert isinstance(local, LocalBlobStore)
    assert isinstance(remote, GcsBlobStore)
