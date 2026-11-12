"""In-memory fake of `AccessFacade`: no I/O, deterministic, no more permissive than the contract."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal

from veranico.modules.access.contracts import (
    Admission,
    Allowance,
    ApiKeyIssued,
    ModelUsage,
    SpendRecorded,
    VisitorRef,
)
from veranico.shared.kernel.clock import Clock, FixedClock
from veranico.shared.kernel.errors import ForbiddenError, RateLimitedError
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal

Call = tuple[str, tuple[object, ...]]


class FakeAccessFacade:
    """Workspaces, API keys, a visitor allowance and a spend ledger kept in dictionaries.

    Knobs a test may set: `ceiling_usd_micros` (spending is refused once the recorded spend
    reaches it; `None` means no ceiling), `ceiling_reason`, and `rate_limited` (key ids whose
    next `check_rate` raises). `calls` lists every call received, in order.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        allowance_code: str | None = "test-allowance-code",
        conversations: int = 2,
        messages: int = 15,
        boosted_conversations: int = 6,
        boosted_messages: int = 60,
        workspace_ttl_days: int = 14,
    ) -> None:
        self._clock = clock or FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
        self._allowance_code = allowance_code
        self._limits = {
            False: (conversations, messages),
            True: (boosted_conversations, boosted_messages),
        }
        self._ttl = timedelta(days=workspace_ttl_days)
        self._cookies: dict[str, WorkspaceId] = {}
        self._keys: dict[str, tuple[str, WorkspaceId]] = {}
        self._used: dict[str, tuple[int, int]] = {}
        self.calls: list[Call] = []
        self.ceiling_usd_micros: int | None = None
        self.ceiling_reason: Literal["day_ceiling", "month_ceiling"] = "day_ceiling"
        self.spent_usd_micros = 0
        self.rate_limited: set[str] = set()

    def visitor(self, client_ip: str, code: str | None) -> VisitorRef:
        self.calls.append(("visitor", (client_ip, code)))
        digest = hashlib.sha256(f"fake-salt:{client_ip}".encode()).hexdigest()
        boosted = self._allowance_code is not None and code == self._allowance_code
        return VisitorRef(ip_hash=digest, boosted=boosted)

    async def open_workspace(self, cookie: str | None) -> tuple[Principal, str | None]:
        self.calls.append(("open_workspace", (cookie,)))
        if cookie is not None and cookie in self._cookies:
            return Principal(workspace_id=self._cookies[cookie], kind="browser"), None
        number = len(self._cookies) + 1
        workspace_id = WorkspaceId(f"ws-{number}")
        new_cookie = f"cookie-{number}"
        self._cookies[new_cookie] = workspace_id
        return Principal(workspace_id=workspace_id, kind="browser"), new_cookie

    async def authenticate_api_key(self, bearer: str) -> Principal:
        self.calls.append(("authenticate_api_key", (bearer,)))
        if bearer not in self._keys:
            raise ForbiddenError
        key_id, workspace_id = self._keys[bearer]
        return Principal(workspace_id=workspace_id, kind="api_key", key_id=key_id)

    async def issue_api_key(self, principal: Principal) -> ApiKeyIssued:
        self.calls.append(("issue_api_key", (principal,)))
        if principal.kind != "browser":
            raise ForbiddenError
        number = len(self._keys) + 1
        key_id, secret = f"key-{number}", f"fake-api-key-{number}"
        self._keys[secret] = (key_id, principal.workspace_id)
        return ApiKeyIssued(key_id=key_id, secret=secret, expires_at=self._clock.now() + self._ttl)

    async def check_rate(self, principal: Principal) -> None:
        self.calls.append(("check_rate", (principal,)))
        if principal.key_id is not None and principal.key_id in self.rate_limited:
            raise RateLimitedError

    async def allowance(self, visitor: VisitorRef) -> Allowance:
        self.calls.append(("allowance", (visitor,)))
        return self._allowance(visitor)

    async def admit_message(self, visitor: VisitorRef, new_conversation: bool) -> Admission:
        self.calls.append(("admit_message", (visitor, new_conversation)))
        allowance = self._allowance(visitor)
        if self._ceiling_reached():
            return Admission(allowed=False, reason=self.ceiling_reason, allowance=allowance)
        if allowance.messages_left < 1 or (new_conversation and allowance.conversations_left < 1):
            return Admission(allowed=False, reason="visitor_allowance", allowance=allowance)
        conversations, messages = self._used.get(visitor.ip_hash, (0, 0))
        self._used[visitor.ip_hash] = (conversations + int(new_conversation), messages + 1)
        return Admission(allowed=True, reason="ok", allowance=self._allowance(visitor))

    async def may_spend(self) -> Admission:
        self.calls.append(("may_spend", ()))
        if self._ceiling_reached():
            return Admission(allowed=False, reason=self.ceiling_reason, allowance=None)
        return Admission(allowed=True, reason="ok", allowance=None)

    async def record_spend(self, usage: ModelUsage) -> SpendRecorded:
        self.calls.append(("record_spend", (usage,)))
        cost = self._cost(usage)
        self.spent_usd_micros += cost
        return SpendRecorded(cost_usd_micros=cost)

    def cost_of(self, usage: ModelUsage) -> int:
        self.calls.append(("cost_of", (usage,)))
        return self._cost(usage)

    @staticmethod
    def _cost(usage: ModelUsage) -> int:
        """One micro-dollar per token of any kind: easy to check by hand in a test."""
        return (
            usage.input_tokens
            + usage.output_tokens
            + usage.cache_read_tokens
            + usage.cache_write_tokens
        )

    def _ceiling_reached(self) -> bool:
        return self.ceiling_usd_micros is not None and (
            self.spent_usd_micros >= self.ceiling_usd_micros
        )

    def _allowance(self, visitor: VisitorRef) -> Allowance:
        conversations, messages = self._limits[visitor.boosted]
        used_conversations, used_messages = self._used.get(visitor.ip_hash, (0, 0))
        now = self._clock.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return Allowance(
            conversations_left=max(conversations - used_conversations, 0),
            messages_left=max(messages - used_messages, 0),
            resets_at=next_midnight,
            boosted=visitor.boosted,
        )
