"""`price_cover`: simulate and price the cover; persists a draft quote through `quoting`.

Pricing is not called directly: `quoting` resolves the grid cell and the dataset from the
coordinates, prices the cover and stores the quote, so the agent and the public API share one
path (SPEC 3.2).
"""

from veranico.modules.assistant.application.tools.models import (
    PriceCoverInput,
    PriceCoverOutput,
    Tool,
    ToolSuccess,
)
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.quoting.contracts import CreateQuote, QuoteLocationInput, QuotingFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "Price a cover and store it as a draft quote. Give the coordinates, label and "
    "administrative region from resolve_location, the index definition and the limit. Call it "
    "only when the user gave or confirmed the location, the window and the limit. Returns the "
    "`quote_id` and `priced`: the backtest, the simulation (expected loss, standard deviation, "
    "probability of payout, 1-in-10 and 1-in-100 payouts), the premium with its rate on line, "
    "and the assumptions. Money is integer BRL centavos in `amount_cents`, with `display`, "
    "the amount already written in reais for the user's language: copy `display` (or round it "
    "to whole reais), never write centavos and never reformat the separators. Rates are "
    "fractions as strings: write them as a percentage only. Always cite the quote by its id "
    '("quote Q-7K3M9P", "cotação Q-7K3M9P") with any of these figures.'
)


def price_cover_tool(quoting: QuotingFacade) -> Tool[PriceCoverInput]:
    async def handler(principal: Principal, arguments: PriceCoverInput) -> ToolSuccess:
        command = CreateQuote(
            location=QuoteLocationInput(
                lat=arguments.lat,
                lon=arguments.lon,
                label=arguments.label,
                admin_region=arguments.admin_region,
            ),
            cover=arguments.cover(),
            simulation=SimulationOptions(n=arguments.n, seed=arguments.seed),
        )
        quote = await quoting.create_quote(principal, command, idempotency_key=None, actor="agent")
        summary = Coded(
            code="tool.price_cover",
            params={
                "quote_id": quote.quote_id,
                "premium_cents": quote.priced.premium.premium.amount_cents,
            },
        )
        output = PriceCoverOutput(quote_id=quote.quote_id, priced=quote.priced)
        return ToolSuccess(output=output, summary=summary)

    return Tool(
        name="price_cover",
        description=DESCRIPTION,
        input_model=PriceCoverInput,
        handler=handler,
    )
