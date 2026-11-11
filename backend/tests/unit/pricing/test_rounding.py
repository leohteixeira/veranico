"""Boundary rounding (SPEC 5.7)."""

import math
import re

import pytest

from veranico.modules.pricing.domain.rounding import (
    cents_difference,
    to_cents,
    to_rate,
    to_tenth,
)

RATE_PATTERN = re.compile(r"^-?\d+\.\d{6}$")  # the kernel's `Rate`


@pytest.mark.req("R-5.7-1")
@pytest.mark.parametrize(
    ("simulated", "historical", "gap"),
    [
        (1_250_000, 1_000_000, 250_000),  # simulation above history
        (900_000, 1_000_000, -100_000),  # below: the gap may be negative
        (1_000_000, 1_000_000, 0),
    ],
)
def test_cents_difference_is_the_first_figure_minus_the_second(
    simulated: int, historical: int, gap: int
) -> None:
    result = cents_difference(simulated, historical)

    assert result == gap
    assert type(result) is int


@pytest.mark.req("R-5.7-1")
@pytest.mark.parametrize(
    ("value", "cents"),
    [
        (0.5, 0),
        (1.5, 2),
        (2.5, 2),
        (3.5, 4),
        (-0.5, 0),
        (-1.5, -2),
        (-2.5, -2),
        (1_234_567.4, 1_234_567),
        (1_234_567.6, 1_234_568),
        (-7.6, -8),
        (0.0, 0),
        (30_000_000.0, 30_000_000),
    ],
)
def test_to_cents_rounds_half_to_even(value: float, cents: int) -> None:
    result = to_cents(value)

    assert result == cents
    assert type(result) is int


@pytest.mark.req("R-5.7-1")
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_to_cents_rejects_a_value_that_is_not_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        to_cents(value)


@pytest.mark.req("R-5.7-2")
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.0583333, "0.058333"),
        (1, "1.000000"),
        (0, "0.000000"),
        (-0.0000001, "0.000000"),  # never "-0.000000"
        (-0.0, "0.000000"),
        (-0.000001, "-0.000001"),
        (0.5, "0.500000"),
        (0.1234567, "0.123457"),
        (-12.5, "-12.500000"),
    ],
)
def test_to_rate_has_exactly_six_decimal_places(value: float, text: str) -> None:
    result = to_rate(value)

    assert result == text
    assert RATE_PATTERN.fullmatch(result)


@pytest.mark.req("R-5.7-2")
@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_to_rate_rejects_a_value_that_is_not_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        to_rate(value)


@pytest.mark.req("R-5.7-3")
@pytest.mark.parametrize(
    ("value", "tenth"),
    [(25.3333, 25.3), (25.36, 25.4), (0.0, 0.0), (17.0, 17.0), (-12.449, -12.4)],
)
def test_to_tenth_rounds_to_one_decimal_place(value: float, tenth: float) -> None:
    assert to_tenth(value) == tenth


@pytest.mark.req("R-5.7-3")
def test_to_tenth_never_returns_negative_zero() -> None:
    assert math.copysign(1.0, to_tenth(-0.04)) == 1.0


@pytest.mark.req("R-5.7-3")
def test_to_tenth_rejects_a_value_that_is_not_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        to_tenth(math.nan)
