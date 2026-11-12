"""`backtest_index`: how the proposed cover would have paid in every season on record."""

from veranico.modules.assistant.application.tools.models import (
    BacktestIndexInput,
    Tool,
    ToolSuccess,
)
from veranico.modules.pricing.contracts import PricingFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "Backtest an index over every season available in a dataset. Call it only when the user "
    "gave the window and the limit; when one is missing, ask for it instead. Returns "
    "per-season index values and payouts, and the aggregates: seasons used and excluded, "
    "`trigger_frequency` "
    "(share of seasons that paid), `burn_cost` (average historical payout), the largest payout "
    "and its season, the trend of the index and warnings. Money is integer BRL centavos in "
    "`amount_cents`: write it in reais, never in centavos (1234567 is R$ 12,345.67 in English "
    "and R$ 12.345,67 in Portuguese); rates are fractions as strings: write them as a "
    'percentage only ("0.125000" is 12.5%). It persists nothing and gives no price: use '
    "price_cover for a premium."
)


def backtest_index_tool(pricing: PricingFacade) -> Tool[BacktestIndexInput]:
    async def handler(principal: Principal, arguments: BacktestIndexInput) -> ToolSuccess:
        result = await pricing.backtest(DatasetId(arguments.dataset_id), arguments.cover())
        summary = Coded(
            code="tool.backtest_index",
            params={
                "seasons_used": result.seasons_used,
                "trigger_frequency_rate": result.trigger_frequency,
            },
        )
        return ToolSuccess(output=result, summary=summary)

    return Tool(
        name="backtest_index",
        description=DESCRIPTION,
        input_model=BacktestIndexInput,
        handler=handler,
    )
