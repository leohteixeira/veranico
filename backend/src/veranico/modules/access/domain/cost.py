"""Cost of a model call in integer micro-dollars. No float anywhere."""

from collections.abc import Mapping
from dataclasses import dataclass

_TOKENS_PER_PRICE_UNIT = 1_000_000


@dataclass(frozen=True, slots=True)
class TokenPrices:
    """Integer micro-dollars per million tokens, per token class."""

    input: int
    output: int
    cache_read: int
    cache_write: int


class UnknownModelPriceError(LookupError):
    """A model has no prices in configuration. A missing price is never treated as zero."""

    def __init__(self, model: str) -> None:
        super().__init__(f"no prices configured for model {model!r}")
        self.model = model


def prices_for(prices: Mapping[str, TokenPrices], model: str) -> TokenPrices:
    try:
        return prices[model]
    except KeyError:
        raise UnknownModelPriceError(model) from None


def cost_usd_micros(
    prices: TokenPrices,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    """Sum tokens times price over the four classes, divide once, round up.

    Rounding up means the ledger never undercounts.
    """
    total = (
        input_tokens * prices.input
        + output_tokens * prices.output
        + cache_read_tokens * prices.cache_read
        + cache_write_tokens * prices.cache_write
    )
    return -(-total // _TOKENS_PER_PRICE_UNIT)
