"""`access_api_keys/{key_id}`: the hash of the secret, never the secret.

Fields: `workspace_id`, `secret_hash`, `created_at`, `expires_at` (the TTL field, copied
from the workspace) and optionally `revoked_at`, which only an operator sets.
"""

from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.ports import ApiKeyRecord
from veranico.shared.kernel.ids import WorkspaceId

COLLECTION = "access_api_keys"


class FirestoreApiKeyStore:
    def __init__(self, client: AsyncClient) -> None:
        self._collection = client.collection(COLLECTION)

    async def create(self, record: ApiKeyRecord) -> None:
        await self._collection.document(record.key_id).create(
            {
                "workspace_id": record.workspace_id,
                "secret_hash": record.secret_hash,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
            }
        )

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        snapshot = await self._collection.document(key_id).get()
        data = snapshot.to_dict()
        if data is None:
            return None
        return ApiKeyRecord(
            key_id=key_id,
            workspace_id=WorkspaceId(data["workspace_id"]),
            secret_hash=data["secret_hash"],
            created_at=data["created_at"],
            expires_at=data["expires_at"],
            revoked_at=data.get("revoked_at"),
        )
