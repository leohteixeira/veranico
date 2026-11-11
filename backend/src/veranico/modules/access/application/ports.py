"""Ports of `access`: the records it keeps and the stores that keep them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from veranico.modules.access.domain.allowance import Limits, Usage
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


class AllowanceStore(Protocol):
    """Usage of one visitor on one UTC day (`day` is `YYYYMMDD`)."""

    async def usage(self, ip_hash: str, day: str) -> Usage: ...

    async def consume(
        self,
        ip_hash: str,
        day: str,
        *,
        limits: Limits,
        new_conversation: bool,
        expires_at: datetime,
    ) -> tuple[Usage, bool]:
        """Count one message when the limits allow it, atomically.

        Returns the usage afterwards and whether the message was counted. Two concurrent
        calls never both take the last slot.
        """
        ...


CeilingReason = Literal["day_ceiling", "month_ceiling"]


class SpendCeilings(Protocol):
    async def reached(self) -> CeilingReason | None:
        """The ceiling that refuses a model call now, or `None` when spending is allowed."""
        ...
