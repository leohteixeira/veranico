"""The spend ledger: what the model calls cost, and the ceilings across all visitors."""

from collections.abc import Mapping
from datetime import UTC

from veranico.modules.access.application.ports import CeilingReason, SpendStore
from veranico.modules.access.contracts import Admission, ModelUsage, SpendRecorded
from veranico.modules.access.domain.cost import TokenPrices, cost_usd_micros, prices_for
from veranico.shared.kernel.clock import Clock


class Spend:
    def __init__(
        self,
        store: SpendStore,
        clock: Clock,
        *,
        prices: Mapping[str, TokenPrices],
        day_ceiling_usd_micros: int,
        month_ceiling_usd_micros: int,
    ) -> None:
        self._store = store
        self._clock = clock
        self._prices = prices
        self._day_ceiling = day_ceiling_usd_micros
        self._month_ceiling = month_ceiling_usd_micros

    def cost_of(self, usage: ModelUsage) -> int:
        """Micro-dollars of one call. A model without prices raises; it never costs zero."""
        return cost_usd_micros(
            prices_for(self._prices, usage.model),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
        )

    async def reached(self) -> CeilingReason | None:
        """The ceiling that refuses a call now; the day ceiling when both are reached."""
        day_total, month_total = await self._store.totals(*self._keys())
        if day_total >= self._day_ceiling:
            return "day_ceiling"
        if month_total >= self._month_ceiling:
            return "month_ceiling"
        return None

    async def may_spend(self) -> Admission:
        """Checked before each model call. There is no visitor here, so no allowance."""
        ceiling = await self.reached()
        if ceiling is not None:
            return Admission(allowed=False, reason=ceiling, allowance=None)
        return Admission(allowed=True, reason="ok", allowance=None)

    async def record(self, usage: ModelUsage) -> SpendRecorded:
        """Charged after each model call. Never refused: a call in flight when a ceiling
        is reached overshoots it by its own cost."""
        cost = self.cost_of(usage)
        day, month = self._keys()
        await self._store.add(day, month, cost)
        return SpendRecorded(cost_usd_micros=cost)

    def _keys(self) -> tuple[str, str]:
        """The UTC day and month of now, from one reading of the clock."""
        now = self._clock.now().astimezone(UTC)
        return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
