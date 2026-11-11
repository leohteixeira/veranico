"""`find_extreme_seasons`: the worst seasons on record for a window."""

from veranico.modules.assistant.application.tools.models import (
    ExtremeSeasonsOutput,
    FindExtremeSeasonsInput,
    Tool,
    ToolSuccess,
)
from veranico.modules.pricing.contracts import PricingFacade, Window
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "List the worst historical seasons for a window: the driest totals for rainfall_below, the "
    "longest dry spells for dry_spell_above. Returns `seasons`, worst first, each with the "
    "season's start year, its index value, its rank and its empirical return period in years."
)


def find_extreme_seasons_tool(pricing: PricingFacade) -> Tool[FindExtremeSeasonsInput]:
    async def handler(principal: Principal, arguments: FindExtremeSeasonsInput) -> ToolSuccess:
        seasons = await pricing.extreme_seasons(
            DatasetId(arguments.dataset_id),
            arguments.index_type,
            Window(start=arguments.window_start, end=arguments.window_end),
            arguments.top_n,
        )
        summary = Coded(code="tool.find_extreme_seasons", params={"count": len(seasons)})
        return ToolSuccess(output=ExtremeSeasonsOutput(seasons=seasons), summary=summary)

    return Tool(
        name="find_extreme_seasons",
        description=DESCRIPTION,
        input_model=FindExtremeSeasonsInput,
        handler=handler,
    )
