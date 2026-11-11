"""In-memory stores for the ports of `access`, for unit tests.

Each keeps public dictionaries, so a test can read what was stored and act as the
operator (for example by setting `revoked_at` on a key), and counts its reads.
"""

from veranico.modules.access.application.ports import ApiKeyRecord, Workspace
from veranico.shared.kernel.ids import WorkspaceId


class MemoryWorkspaceStore:
    def __init__(self) -> None:
        self.workspaces: dict[WorkspaceId, Workspace] = {}
        self.reads = 0

    async def create(self, workspace: Workspace) -> None:
        assert workspace.workspace_id not in self.workspaces
        self.workspaces[workspace.workspace_id] = workspace

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        self.reads += 1
        return self.workspaces.get(workspace_id)


class MemoryApiKeyStore:
    def __init__(self) -> None:
        self.keys: dict[str, ApiKeyRecord] = {}
        self.reads = 0

    async def create(self, record: ApiKeyRecord) -> None:
        assert record.key_id not in self.keys
        self.keys[record.key_id] = record

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        self.reads += 1
        return self.keys.get(key_id)
