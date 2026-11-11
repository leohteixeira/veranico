import secrets
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.api_keys import ApiKeys
from veranico.modules.access.application.workspaces import Workspaces
from veranico.modules.access.domain import api_key_token
from veranico.modules.access.infrastructure.firestore_api_keys import (
    COLLECTION,
    FirestoreApiKeyStore,
)
from veranico.modules.access.infrastructure.firestore_workspaces import FirestoreWorkspaceStore
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import ForbiddenError
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LIFETIME = timedelta(days=14)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def workspaces(firestore: AsyncClient, clock: FixedClock) -> Workspaces:
    return Workspaces(
        FirestoreWorkspaceStore(firestore),
        clock,
        signing_secret=secrets.token_hex(16),
        lifetime=LIFETIME,
    )


@pytest.fixture
def api_keys(firestore: AsyncClient, clock: FixedClock) -> ApiKeys:
    return ApiKeys(FirestoreApiKeyStore(firestore), FirestoreWorkspaceStore(firestore), clock)


async def _browser(workspaces: Workspaces) -> Principal:
    principal, _ = await workspaces.open(None)
    return principal


@pytest.mark.req("R-10.2-1", "R-10.2-4", "R-10.1-3")
async def test_the_document_holds_the_hash_the_expiry_and_no_secret(
    api_keys: ApiKeys, workspaces: Workspaces, firestore: AsyncClient
) -> None:
    browser = await _browser(workspaces)

    issued = await api_keys.issue(browser)

    snapshot = await firestore.collection(COLLECTION).document(issued.key_id).get()
    data = snapshot.to_dict()
    assert data is not None
    assert set(data) == {"workspace_id", "secret_hash", "created_at", "expires_at"}
    assert data["workspace_id"] == browser.workspace_id
    # A TTL policy needs a "Date and time" value: the client returns one as a datetime.
    assert isinstance(data["expires_at"], datetime)
    assert data["expires_at"] == issued.expires_at == NOW + LIFETIME
    parsed = api_key_token.parse_bearer(issued.secret)
    assert parsed is not None
    secret = parsed[1]
    assert data["secret_hash"] == api_key_token.hash_secret(secret)
    stored = repr(data)
    assert secret not in stored
    assert not any(secret[i : i + 8] in stored for i in range(len(secret) - 7))


@pytest.mark.req("R-10.2-2", "R-10.1-2")
async def test_a_key_authenticates_into_its_own_workspace_only(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    browser_a, browser_b = await _browser(workspaces), await _browser(workspaces)
    key_a, key_b = await api_keys.issue(browser_a), await api_keys.issue(browser_b)

    principal_a = await api_keys.authenticate(key_a.secret)
    principal_b = await api_keys.authenticate(key_b.secret)

    assert principal_a == Principal(
        workspace_id=browser_a.workspace_id, kind="api_key", key_id=key_a.key_id
    )
    assert principal_b.workspace_id == browser_b.workspace_id


@pytest.mark.req("R-10.2-2")
async def test_unknown_key_wrong_secret_and_malformed_bearer_are_forbidden(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))
    unknown_id, other_secret = api_key_token.mint()

    for bearer in (
        api_key_token.format_bearer(unknown_id, other_secret),
        api_key_token.format_bearer(issued.key_id, other_secret),
        "vrk_a/b_secret",
        "",
    ):
        with pytest.raises(ForbiddenError):
            await api_keys.authenticate(bearer)


@pytest.mark.req("R-10.2-1")
async def test_an_api_key_principal_cannot_mint_a_key(
    api_keys: ApiKeys, workspaces: Workspaces
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))

    with pytest.raises(ForbiddenError):
        await api_keys.issue(await api_keys.authenticate(issued.secret))


@pytest.mark.req("R-10.2-4")
async def test_issue_is_refused_for_a_missing_or_expired_workspace(
    api_keys: ApiKeys, workspaces: Workspaces, clock: FixedClock
) -> None:
    browser = await _browser(workspaces)

    with pytest.raises(ForbiddenError):
        await api_keys.issue(
            Principal(workspace_id=WorkspaceId(secrets.token_hex(16)), kind="browser")
        )
    clock.advance(LIFETIME)
    with pytest.raises(ForbiddenError):
        await api_keys.issue(browser)


@pytest.mark.req("R-10.2-4")
async def test_a_key_past_its_expiry_is_forbidden_while_its_document_still_exists(
    api_keys: ApiKeys, workspaces: Workspaces, clock: FixedClock, firestore: AsyncClient
) -> None:
    issued = await api_keys.issue(await _browser(workspaces))

    clock.advance(LIFETIME)

    # TTL deletion is not immediate: the document is still there and must not authenticate.
    assert (await firestore.collection(COLLECTION).document(issued.key_id).get()).exists
    with pytest.raises(ForbiddenError):
        await api_keys.authenticate(issued.secret)


@pytest.mark.req("R-10.2-5")
async def test_an_operator_revokes_a_key_by_setting_revoked_at_on_its_document(
    api_keys: ApiKeys, workspaces: Workspaces, firestore: AsyncClient
) -> None:
    browser = await _browser(workspaces)
    revoked, kept = await api_keys.issue(browser), await api_keys.issue(browser)
    assert (await api_keys.authenticate(revoked.secret)).key_id == revoked.key_id

    await firestore.collection(COLLECTION).document(revoked.key_id).update({"revoked_at": NOW})

    with pytest.raises(ForbiddenError):
        await api_keys.authenticate(revoked.secret)
    assert (await api_keys.authenticate(kept.secret)).key_id == kept.key_id
