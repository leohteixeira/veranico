"""The `AccessFacade` of the module: it only composes the services of this package."""

from veranico.modules.access.application.allowances import Allowances
from veranico.modules.access.application.api_keys import ApiKeys
from veranico.modules.access.application.rate_limit import RateLimiter
from veranico.modules.access.application.spend import Spend
from veranico.modules.access.application.workspaces import Workspaces
from veranico.modules.access.contracts import (
    Admission,
    Allowance,
    ApiKeyIssued,
    ModelUsage,
    SpendRecorded,
    VisitorRef,
)
from veranico.modules.access.domain import visitor as visitor_rules
from veranico.shared.kernel.principal import Principal


class Access:
    def __init__(
        self,
        *,
        workspaces: Workspaces,
        api_keys: ApiKeys,
        rate_limiter: RateLimiter,
        allowances: Allowances,
        spend: Spend,
        ip_hash_salt: str,
        allowance_code: str | None,
    ) -> None:
        self._workspaces = workspaces
        self._api_keys = api_keys
        self._rate_limiter = rate_limiter
        self._allowances = allowances
        self._spend = spend
        self._ip_hash_salt = ip_hash_salt
        self._allowance_code = allowance_code

    def visitor(self, client_ip: str, code: str | None) -> VisitorRef:
        """The address and the code stop here: only the hash and the flag go on."""
        return VisitorRef(
            ip_hash=visitor_rules.hash_address(client_ip, self._ip_hash_salt),
            boosted=visitor_rules.is_boosted(code, self._allowance_code),
        )

    async def open_workspace(self, cookie: str | None) -> tuple[Principal, str | None]:
        return await self._workspaces.open(cookie)

    async def authenticate_api_key(self, bearer: str) -> Principal:
        return await self._api_keys.authenticate(bearer)

    async def issue_api_key(self, principal: Principal) -> ApiKeyIssued:
        return await self._api_keys.issue(principal)

    async def check_rate(self, principal: Principal) -> None:
        self._rate_limiter.check(principal)

    async def allowance(self, visitor: VisitorRef) -> Allowance:
        return await self._allowances.allowance(visitor)

    async def admit_message(self, visitor: VisitorRef, new_conversation: bool) -> Admission:
        return await self._allowances.admit_message(visitor, new_conversation)

    async def may_spend(self) -> Admission:
        return await self._spend.may_spend()

    async def record_spend(self, usage: ModelUsage) -> SpendRecorded:
        return await self._spend.record(usage)

    def cost_of(self, usage: ModelUsage) -> int:
        return self._spend.cost_of(usage)
