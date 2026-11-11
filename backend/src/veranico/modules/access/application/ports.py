"""Ports of `access`: the records it keeps and the stores that keep them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from veranico.shared.kernel.ids import WorkspaceId


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: WorkspaceId
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    key_id: str
    workspace_id: WorkspaceId
    secret_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None  # set by an operator on the document; there is no route


class WorkspaceStore(Protocol):
    async def create(self, workspace: Workspace) -> None: ...
    async def get(self, workspace_id: WorkspaceId) -> Workspace | None: ...


class ApiKeyStore(Protocol):
    async def create(self, record: ApiKeyRecord) -> None: ...
    async def get(self, key_id: str) -> ApiKeyRecord | None: ...
