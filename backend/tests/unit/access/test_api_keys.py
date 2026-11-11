import dataclasses
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.access.memory import MemoryApiKeyStore, MemoryWorkspaceStore
from veranico.modules.access.application.api_keys import ApiKeys
from veranico.modules.access.application.workspaces import Workspaces
from veranico.modules.access.domain import api_key_token
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import ForbiddenError
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LIFETIME = timedelta(days=14)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def workspace_store() -> MemoryWorkspaceStore:
    return MemoryWorkspaceStore()


@pytest.fixture
def key_store() -> MemoryApiKeyStore:
    return MemoryApiKeyStore()


@pytest.fixture
def workspaces(workspace_store: MemoryWorkspaceStore, clock: FixedClock) -> Workspaces:
    return Workspaces(
        workspace_store, clock, signing_secret=secrets.token_hex(16), lifetime=LIFETIME
    )


@pytest.fixture
def api_keys(
    key_store: MemoryApiKeyStore, workspace_store: MemoryWorkspaceStore, clock: FixedClock
) -> ApiKeys:
    return ApiKeys(key_store, workspace_store, clock)


async def _browser(workspaces: Workspaces) -> Principal:
    principal, _ = await workspaces.open(None)
    return principal


@pytest.mark.req("R-10.2-1", "R-10.2-4")
async def test_issue_returns_a_secret_once_and_stores_only_its_hash(
    api_keys: ApiKeys, workspaces: Workspaces, key_store: MemoryApiKeyStore
) -> None:
    browser = await _browser(workspaces)

    issued = await api_keys.issue(browser)

    assert issued.expires_at == NOW + LIFETIME  # the workspace's expiry
    parsed = api_key_token.parse_bearer(issued.secret)
    assert parsed is not None
    key_id, secret = parsed
    assert key_id == issued.key_id
    record = key_store.keys[issued.key_id]
    assert record.workspace_id == browser.workspace_id
    assert record.expires_at == issued.expires_at
    assert record.revoked_at is None
    stored = repr(dataclasses.asdict(record))
    assert secret not in stored
    assert issued.secret not in stored
    # No piece of the secret either: every 8-character window of it is absent.
    assert not any(secret[i : i + 8] in stored for i in range(len(secret) - 7))


@pytest.mark.req("R-10.2-1")
async def test_two_keys_of_one_workspace_differ(api_keys: ApiKeys, workspaces: Workspaces) -> None:
    browser = await _browser(workspaces)

    first, second = await api_keys.issue(browser), await api_keys.issue(browser)

    assert first.key_id != second.key_id
    assert first.secret != second.secret


@pytest.mark.req("R-10.2-1")
async def test_an_api_key_principal_cannot_mint_a_key(
    api_keys: ApiKeys, workspaces: Workspaces, key_store: MemoryApiKeyStore
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))
    key_principal = await api_keys.authenticate(issued.secret)

    with pytest.raises(ForbiddenError):
        await api_keys.issue(key_principal)
    with pytest.raises(ForbiddenError):
        await api_keys.issue(Principal(workspace_id=key_principal.workspace_id, kind="system"))

    assert len(key_store.keys) == 1


@pytest.mark.req("R-10.2-4")
async def test_issue_is_refused_for_a_missing_or_expired_workspace(
    api_keys: ApiKeys, workspaces: Workspaces, clock: FixedClock
) -> None:
    browser = await _browser(workspaces)

    with pytest.raises(ForbiddenError):
        await api_keys.issue(Principal(workspace_id=WorkspaceId("0" * 32), kind="browser"))
    clock.advance(LIFETIME)
    with pytest.raises(ForbiddenError):
        await api_keys.issue(browser)


@pytest.mark.req("R-10.2-2")
async def test_authenticate_returns_the_issuing_workspace_and_key_id(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    browser = await _browser(workspaces)
    issued = await api_keys.issue(browser)

    principal = await api_keys.authenticate(issued.secret)

    assert principal == Principal(
        workspace_id=browser.workspace_id, kind="api_key", key_id=issued.key_id
    )


@pytest.mark.req("R-10.2-2", "R-10.1-2")
async def test_a_key_of_one_workspace_never_yields_another(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    browser_a, browser_b = await _browser(workspaces), await _browser(workspaces)
    key_a, key_b = await api_keys.issue(browser_a), await api_keys.issue(browser_b)

    assert (await api_keys.authenticate(key_a.secret)).workspace_id == browser_a.workspace_id
    assert (await api_keys.authenticate(key_b.secret)).workspace_id == browser_b.workspace_id
    # The id of key B with the secret of key A opens nothing.
    _, secret_a = api_key_token.parse_bearer(key_a.secret) or ("", "")
    with pytest.raises(ForbiddenError):
        await api_keys.authenticate(api_key_token.format_bearer(key_b.key_id, secret_a))


@pytest.mark.req("R-10.2-2")
async def test_unknown_key_wrong_secret_and_malformed_bearer_are_the_same_forbidden(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))
    _, other_secret = api_key_token.mint()
    attempts = [
        api_key_token.format_bearer("0123456789abcdef", other_secret),  # unknown key id
        api_key_token.format_bearer(issued.key_id, other_secret),  # wrong secret
        issued.secret + "x",
        issued.secret[:-1],
        issued.key_id,
        "",
        "not-a-key",
        "vrk_../x_secret",
    ]

    errors = []
    for bearer in attempts:
        with pytest.raises(ForbiddenError) as raised:
            await api_keys.authenticate(bearer)
        errors.append((type(raised.value), raised.value.code, raised.value.detail))

    assert set(errors) == {(ForbiddenError, "forbidden", None)}


@pytest.mark.req("R-10.2-4")
async def test_a_key_past_its_expiry_is_forbidden(
    api_keys: ApiKeys, workspaces: Workspaces, clock: FixedClock
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))

    clock.advance(LIFETIME - timedelta(seconds=1))
    assert (await api_keys.authenticate(issued.secret)).key_id == issued.key_id
    clock.advance(timedelta(seconds=1))
    with pytest.raises(ForbiddenError):
        await api_keys.authenticate(issued.secret)


@pytest.mark.req("R-10.2-5")
async def test_a_key_with_revoked_at_set_is_forbidden(
    api_keys: ApiKeys, workspaces: Workspaces, key_store: MemoryApiKeyStore
) -> None:
    browser = await _browser(workspaces)
    revoked, kept = await api_keys.issue(browser), await api_keys.issue(browser)

    # The operator's action: there is no route and no facade method for it.
    key_store.keys[revoked.key_id] = dataclasses.replace(
        key_store.keys[revoked.key_id], revoked_at=NOW
    )

    with pytest.raises(ForbiddenError):
        await api_keys.authenticate(revoked.secret)
    assert (await api_keys.authenticate(kept.secret)).key_id == kept.key_id
