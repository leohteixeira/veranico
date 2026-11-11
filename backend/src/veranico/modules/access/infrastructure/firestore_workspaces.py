"""`access_workspaces/{workspace_id}`: `created_at`, `expires_at` (the TTL field)."""

from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.ports import Workspace
from veranico.shared.kernel.ids import WorkspaceId

COLLECTION = "access_workspaces"


class FirestoreWorkspaceStore:
    def __init__(self, client: AsyncClient) -> None:
        self._collection = client.collection(COLLECTION)

    async def create(self, workspace: Workspace) -> None:
        # Datetimes are stored as Firestore timestamps, the type a TTL policy needs.
        await self._collection.document(workspace.workspace_id).create(
            {"created_at": workspace.created_at, "expires_at": workspace.expires_at}
        )

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        snapshot = await self._collection.document(workspace_id).get()
        data = snapshot.to_dict()
        if data is None:
            return None
        return Workspace(
            workspace_id=workspace_id,
            created_at=data["created_at"],
            expires_at=data["expires_at"],
        )
