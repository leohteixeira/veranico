"""API keys of a workspace: minted for a browser, shown once, stored as a hash."""

from veranico.modules.access.application.ports import ApiKeyRecord, ApiKeyStore, WorkspaceStore
from veranico.modules.access.contracts import ApiKeyIssued
from veranico.modules.access.domain import api_key_token
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import ForbiddenError
from veranico.shared.kernel.principal import Principal

# Compared against when no key has the presented id, so an unknown key and a wrong secret
# do the same work. No secret hashes to it.
_NO_KEY_HASH = "0" * 64


class ApiKeys:
    def __init__(self, keys: ApiKeyStore, workspaces: WorkspaceStore, clock: Clock) -> None:
        self._keys = keys
        self._workspaces = workspaces
        self._clock = clock

    async def issue(self, principal: Principal) -> ApiKeyIssued:
        """Mint a key for the workspace of a browser principal. A key cannot mint keys."""
        if principal.kind != "browser":
            raise ForbiddenError
        now = self._clock.now()
        workspace = await self._workspaces.get(principal.workspace_id)
        if workspace is None or workspace.expires_at <= now:
            raise ForbiddenError
        key_id, secret = api_key_token.mint()
        await self._keys.create(
            ApiKeyRecord(
                key_id=key_id,
                workspace_id=workspace.workspace_id,
                secret_hash=api_key_token.hash_secret(secret),
                created_at=now,
                expires_at=workspace.expires_at,  # a key expires with its workspace
            )
        )
        return ApiKeyIssued(
            key_id=key_id,
            secret=api_key_token.format_bearer(key_id, secret),
            expires_at=workspace.expires_at,
        )

    async def authenticate(self, bearer: str) -> Principal:
        """Return the API key principal of a bearer. Every failure is the same `forbidden`."""
        parsed = api_key_token.parse_bearer(bearer)
        if parsed is None:
            raise ForbiddenError
        key_id, secret = parsed
        record = await self._keys.get(key_id)
        matches = api_key_token.secret_matches(
            secret, record.secret_hash if record is not None else _NO_KEY_HASH
        )
        # Expiry and revocation are checked here: TTL deletion is not immediate.
        if (
            record is None
            or not matches
            or record.expires_at <= self._clock.now()
            or record.revoked_at is not None
        ):
            raise ForbiddenError
        return Principal(workspace_id=record.workspace_id, kind="api_key", key_id=record.key_id)
