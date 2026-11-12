import secrets
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.access.memory import MemoryWorkspaceStore
from veranico.modules.access.application.workspaces import Workspaces
from veranico.shared.kernel.clock import FixedClock

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LIFETIME = timedelta(days=14)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def store() -> MemoryWorkspaceStore:
    return MemoryWorkspaceStore()


@pytest.fixture
def workspaces(store: MemoryWorkspaceStore, clock: FixedClock) -> Workspaces:
    return Workspaces(store, clock, signing_secret=secrets.token_hex(16), lifetime=LIFETIME)


@pytest.mark.req("R-10-1", "R-10.1-1", "R-10.1-3")
async def test_no_cookie_opens_a_workspace_expiring_after_the_lifetime(
    workspaces: Workspaces, store: MemoryWorkspaceStore
) -> None:
    principal, cookie = await workspaces.open(None)

    assert principal.kind == "browser"
    assert principal.key_id is None
    assert cookie is not None
    stored = store.workspaces[principal.workspace_id]
    assert stored.created_at == NOW
    assert stored.expires_at == NOW + LIFETIME


@pytest.mark.req("R-10.1-1")
async def test_issued_cookie_returns_the_same_workspace_without_a_store_read(
    workspaces: Workspaces, store: MemoryWorkspaceStore
) -> None:
    principal, cookie = await workspaces.open(None)

    again, new_cookie = await workspaces.open(cookie)

    assert again == principal
    assert new_cookie is None
    assert store.reads == 0
    assert len(store.workspaces) == 1


@pytest.mark.req("R-10.1-1", "R-10.1-2")
async def test_tampered_cookie_opens_a_different_workspace(
    workspaces: Workspaces, store: MemoryWorkspaceStore
) -> None:
    victim, victim_cookie = await workspaces.open(None)
    attacker, attacker_cookie = await workspaces.open(None)
    assert victim_cookie is not None
    assert attacker_cookie is not None
    # The attacker's valid signature on the victim's workspace id.
    version, _, expires, signature = attacker_cookie.split(".")
    forged = f"{version}.{victim.workspace_id}.{expires}.{signature}"

    principal, new_cookie = await workspaces.open(forged)

    assert principal.workspace_id not in (victim.workspace_id, attacker.workspace_id)
    assert new_cookie is not None
    assert len(store.workspaces) == 3


@pytest.mark.req("R-10-1")
@pytest.mark.parametrize("cookie", ["", "garbage", "v1.a.b.c", "cookie-1"])
async def test_malformed_cookie_opens_a_new_workspace_and_raises_nothing(
    workspaces: Workspaces, cookie: str
) -> None:
    principal, new_cookie = await workspaces.open(cookie)

    assert principal.kind == "browser"
    assert new_cookie is not None


@pytest.mark.req("R-10.1-1")
async def test_cookie_signed_with_another_secret_opens_a_new_workspace(
    store: MemoryWorkspaceStore, clock: FixedClock
) -> None:
    other = Workspaces(store, clock, signing_secret=secrets.token_hex(16), lifetime=LIFETIME)
    workspaces = Workspaces(store, clock, signing_secret=secrets.token_hex(16), lifetime=LIFETIME)
    foreign, foreign_cookie = await other.open(None)

    principal, new_cookie = await workspaces.open(foreign_cookie)

    assert principal.workspace_id != foreign.workspace_id
    assert new_cookie is not None


@pytest.mark.req("R-10.1-3")
async def test_cookie_past_its_expiry_opens_a_different_workspace(
    workspaces: Workspaces, clock: FixedClock
) -> None:
    principal, cookie = await workspaces.open(None)

    clock.advance(LIFETIME - timedelta(seconds=1))
    still, none = await workspaces.open(cookie)
    clock.advance(timedelta(seconds=1))
    later, new_cookie = await workspaces.open(cookie)

    assert still == principal
    assert none is None
    assert later.workspace_id != principal.workspace_id
    assert new_cookie is not None
    assert new_cookie != cookie


@pytest.mark.req("R-10.1-3")
async def test_use_does_not_extend_the_lifetime(
    workspaces: Workspaces, store: MemoryWorkspaceStore, clock: FixedClock
) -> None:
    principal, cookie = await workspaces.open(None)

    clock.advance(timedelta(days=7))
    await workspaces.open(cookie)

    assert store.workspaces[principal.workspace_id].expires_at == NOW + LIFETIME


@pytest.mark.req("R-10.1-1")
async def test_two_browsers_get_two_workspaces(workspaces: Workspaces) -> None:
    first, first_cookie = await workspaces.open(None)
    second, second_cookie = await workspaces.open(None)

    assert first.workspace_id != second.workspace_id
    assert first_cookie != second_cookie
