import pytest

from veranico.modules.access.domain.cost import (
    TokenPrices,
    UnknownModelPriceError,
    cost_usd_micros,
    prices_for,
)

pytestmark = pytest.mark.req("R-10.3-3")

# Invented prices, in micro-dollars per million tokens.
PRICES = TokenPrices(input=2_000_000, output=7_000_000, cache_read=300_000, cache_write=5_000_000)


def test_each_token_class_alone() -> None:
    # 3,000,000 tokens at 2,000,000 micro-dollars per million = 6,000,000 micro-dollars.
    assert cost_usd_micros(PRICES, input_tokens=3_000_000, output_tokens=0) == 6_000_000
    # 1,000 tokens at 7,000,000 per million = 7,000.
    assert cost_usd_micros(PRICES, input_tokens=0, output_tokens=1_000) == 7_000
    # 10,000 tokens at 300,000 per million = 3,000.
    assert (
        cost_usd_micros(PRICES, input_tokens=0, output_tokens=0, cache_read_tokens=10_000) == 3_000
    )
    # 200 tokens at 5,000,000 per million = 1,000.
    assert cost_usd_micros(PRICES, input_tokens=0, output_tokens=0, cache_write_tokens=200) == 1_000


def test_classes_combined() -> None:
    cost = cost_usd_micros(
        PRICES,
        input_tokens=3_000_000,
        output_tokens=1_000,
        cache_read_tokens=10_000,
        cache_write_tokens=200,
    )

    assert cost == 6_000_000 + 7_000 + 3_000 + 1_000


def test_zero_tokens_cost_zero() -> None:
    assert cost_usd_micros(PRICES, input_tokens=0, output_tokens=0) == 0


def test_fractional_result_rounds_up_to_the_next_micro_dollar() -> None:
    cheap = TokenPrices(input=1, output=1, cache_read=1, cache_write=1)

    # One token at one micro-dollar per million is a millionth of a micro-dollar.
    assert cost_usd_micros(cheap, input_tokens=1, output_tokens=0) == 1
    assert cost_usd_micros(cheap, input_tokens=1_000_000, output_tokens=0) == 1
    assert cost_usd_micros(cheap, input_tokens=1_000_000, output_tokens=1) == 2


def test_the_division_happens_once_over_the_sum() -> None:
    cheap = TokenPrices(input=1, output=1, cache_read=1, cache_write=1)

    # Four fractions of a quarter micro-dollar each add up to exactly one, not four.
    cost = cost_usd_micros(
        cheap,
        input_tokens=250_000,
        output_tokens=250_000,
        cache_read_tokens=250_000,
        cache_write_tokens=250_000,
    )

    assert cost == 1


def test_large_counts_stay_exact() -> None:
    # 2**60 + 1 is not representable in float64: a float path would lose the last token.
    tokens = 2**60 + 1
    prices = TokenPrices(input=3_000_000, output=0, cache_read=0, cache_write=0)

    assert cost_usd_micros(prices, input_tokens=tokens, output_tokens=0) == 3 * tokens
    assert int(float(tokens)) != tokens  # the premise of this test


def test_cost_is_an_integer() -> None:
    assert type(cost_usd_micros(PRICES, input_tokens=1, output_tokens=1)) is int


def test_model_without_prices_raises() -> None:
    table = {"model-a": PRICES}

    assert prices_for(table, "model-a") is PRICES
    with pytest.raises(UnknownModelPriceError):
        prices_for(table, "model-b")
