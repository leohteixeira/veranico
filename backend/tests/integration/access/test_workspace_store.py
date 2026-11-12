import secrets
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.workspaces import Workspaces
from veranico.modules.access.infrastructure.firestore_workspaces import (
    COLLECTION,
    FirestoreWorkspaceStore,
)
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import WorkspaceId

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LIFETIME = timedelta(days=14)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def store(firestore: AsyncClient) -> FirestoreWorkspaceStore:
    return FirestoreWorkspaceStore(firestore)


@pytest.fixture
def workspaces(store: FirestoreWorkspaceStore, clock: FixedClock) -> Workspaces:
    return Workspaces(store, clock, signing_secret=secrets.token_hex(16), lifetime=LIFETIME)


@pytest.mark.req("R-10-1", "R-10.1-1", "R-10.1-3")
async def test_a_new_workspace_is_stored_with_its_expiry(
    workspaces: Workspaces, store: FirestoreWorkspaceStore
) -> None:
    principal, cookie = await workspaces.open(None)

    stored = await store.get(principal.workspace_id)

    assert cookie is not None
    assert stored is not None
    assert stored.workspace_id == principal.workspace_id
    assert stored.created_at == NOW
    assert stored.expires_at == NOW + LIFETIME


@pytest.mark.req("R-10.1-3")
async def test_the_document_carries_expires_at_as_a_timestamp(
    workspaces: Workspaces, firestore: AsyncClient
) -> None:
    principal, _ = await workspaces.open(None)

    snapshot = await firestore.collection(COLLECTION).document(principal.workspace_id).get()
    data = snapshot.to_dict()

    assert data is not None
    assert set(data) == {"created_at", "expires_at"}
    # A TTL policy needs a "Date and time" value: the client returns one as a datetime.
    assert isinstance(data["expires_at"], datetime)
    assert data["expires_at"].tzinfo is not None
    assert data["expires_at"] == NOW + LIFETIME


@pytest.mark.req("R-10.1-1")
async def test_issued_cookie_returns_the_same_workspace_and_a_tampered_one_does_not(
    workspaces: Workspaces,
) -> None:
    principal, cookie = await workspaces.open(None)
    assert cookie is not None

    again, none = await workspaces.open(cookie)
    other, new_cookie = await workspaces.open(cookie[:-1] + ("0" if cookie[-1] != "0" else "1"))

    assert again == principal
    assert none is None
    assert other.workspace_id != principal.workspace_id
    assert new_cookie is not None


@pytest.mark.req("R-10.1-3")
async def test_cookie_past_its_expiry_opens_a_different_workspace(
    workspaces: Workspaces, clock: FixedClock
) -> None:
    principal, cookie = await workspaces.open(None)

    clock.advance(LIFETIME)
    later, new_cookie = await workspaces.open(cookie)

    assert later.workspace_id != principal.workspace_id
    assert new_cookie is not None


async def test_an_unknown_workspace_is_absent(store: FirestoreWorkspaceStore) -> None:
    assert await store.get(WorkspaceId(secrets.token_hex(16))) is None
