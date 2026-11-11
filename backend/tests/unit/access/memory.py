"""In-memory stores for the ports of `access`, for unit tests.

Each keeps public dictionaries, so a test can read what was stored and act as the
operator (for example by setting `revoked_at` on a key), and counts its reads.
"""

from datetime import datetime

from veranico.modules.access.application.ports import ApiKeyRecord, CeilingReason, Workspace
from veranico.modules.access.domain.allowance import Limits, Usage, consume
from veranico.shared.kernel.ids import WorkspaceId


class MemoryAllowanceStore:
    def __init__(self) -> None:
        self.usages: dict[tuple[str, str], Usage] = {}
        self.expires_at: dict[tuple[str, str], datetime] = {}
        self.writes = 0

    async def usage(self, ip_hash: str, day: str) -> Usage:
        return self.usages.get((ip_hash, day), Usage())

    async def consume(
        self,
        ip_hash: str,
        day: str,
        *,
        limits: Limits,
        new_conversation: bool,
        expires_at: datetime,
    ) -> tuple[Usage, bool]:
        usage = self.usages.get((ip_hash, day), Usage())
        updated = consume(limits, usage, new_conversation)
        if updated is None:
            return usage, False
        self.usages[(ip_hash, day)] = updated
        self.expires_at[(ip_hash, day)] = expires_at
        self.writes += 1
        return updated, True


class StubSpendCeilings:
    """Spend ceilings a test sets by hand."""

    def __init__(self) -> None:
        self.reason: CeilingReason | None = None

    async def reached(self) -> CeilingReason | None:
        return self.reason


class MemorySpendStore:
    def __init__(self) -> None:
        self.days: dict[str, int] = {}
        self.months: dict[str, int] = {}
        self.calls: dict[str, int] = {}
        self.writes = 0

    async def totals(self, day: str, month: str) -> tuple[int, int]:
        return self.days.get(day, 0), self.months.get(month, 0)

    async def add(self, day: str, month: str, cost_usd_micros: int) -> None:
        self.days[day] = self.days.get(day, 0) + cost_usd_micros
        self.months[month] = self.months.get(month, 0) + cost_usd_micros
        for key in (day, month):
            self.calls[key] = self.calls.get(key, 0) + 1
        self.writes += 1


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
