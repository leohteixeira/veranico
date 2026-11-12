"""Anonymous workspaces: one per browser, named by a signed cookie value."""

from datetime import timedelta

from veranico.modules.access.application.ports import Workspace, WorkspaceStore
from veranico.modules.access.domain import workspace_cookie
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.principal import Principal


class Workspaces:
    def __init__(
        self, store: WorkspaceStore, clock: Clock, *, signing_secret: str, lifetime: timedelta
    ) -> None:
        self._store = store
        self._clock = clock
        self._secret = signing_secret
        self._lifetime = lifetime

    async def open(self, cookie: str | None) -> tuple[Principal, str | None]:
        """Return the workspace of a valid cookie, or a new one with the cookie to set.

        A valid, unexpired value is accepted without a read. Anything else counts as no
        cookie: there is no access gate, so the answer is a new workspace and never an
        error. The lifetime is fixed at creation and is not extended by use.
        """
        now = self._clock.now()
        if cookie is not None:
            verified = workspace_cookie.verify(cookie, self._secret, now)
            if verified is not None:
                return Principal(workspace_id=verified[0], kind="browser"), None
        workspace = Workspace(
            workspace_id=workspace_cookie.new_workspace_id(),
            created_at=now,
            expires_at=now + self._lifetime,
        )
        await self._store.create(workspace)
        value = workspace_cookie.sign(workspace.workspace_id, workspace.expires_at, self._secret)
        return Principal(workspace_id=workspace.workspace_id, kind="browser"), value
