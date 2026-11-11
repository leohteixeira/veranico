"""Payout and cover validation (SPEC 5.3), limit R$ 300,000.00 = 30,000,000 centavos."""

import numpy as np
import pytest

from veranico.modules.pricing.domain.errors import InvalidCoverError
from veranico.modules.pricing.domain.index import IndexType
from veranico.modules.pricing.domain.payout import payout_fraction, validate_cover, validate_index

LIMIT_CENTS = 30_000_000


def payout_cents(index_type: IndexType, index: float, trigger: float, exit: float) -> float:
    return float(LIMIT_CENTS * payout_fraction(index_type, index, trigger, exit))


@pytest.mark.req("R-5.3-1")
@pytest.mark.parametrize(
    ("index", "expected_cents"),
    [
        (130.0, 0),  # wetter than the trigger
        (100.0, 0),  # exactly at the trigger
        (85.0, 7_500_000),  # a quarter of the way
        (70.0, 15_000_000),  # halfway
        (40.0, 30_000_000),  # exactly at the exit
        (20.0, 30_000_000),  # beyond the exit: capped at the limit
    ],
)
def test_rainfall_below_pays_linearly_from_trigger_100_to_exit_40(
    index: float, expected_cents: int
) -> None:
    assert payout_cents("rainfall_below", index, 100.0, 40.0) == pytest.approx(
        expected_cents, abs=1e-6
    )


@pytest.mark.req("R-5.3-2")
@pytest.mark.parametrize(
    ("index", "expected_cents"),
    [
        (8.0, 0),  # shorter than the trigger
        (10.0, 0),  # exactly at the trigger
        (13.0, 6_000_000),  # a fifth of the way
        (16.0, 12_000_000),  # two fifths
        (25.0, 30_000_000),  # exactly at the exit
        (40.0, 30_000_000),  # beyond the exit: capped at the limit
    ],
)
def test_dry_spell_above_pays_linearly_from_trigger_10_to_exit_25(
    index: float, expected_cents: int
) -> None:
    assert payout_cents("dry_spell_above", index, 10.0, 25.0) == pytest.approx(
        expected_cents, abs=1e-6
    )


@pytest.mark.req("R-5.3-1")
@pytest.mark.req("R-5.3-2")
def test_payout_fraction_is_vectorised_and_keeps_the_shape() -> None:
    grid = np.array([[130.0, 70.0], [40.0, 20.0]])

    fractions = payout_fraction("rainfall_below", grid, 100.0, 40.0)

    assert fractions.tolist() == [[0.0, 0.5], [1.0, 1.0]]
    assert payout_fraction("dry_spell_above", [8.0, 17.5, 40.0], 10.0, 25.0).tolist() == [
        0.0,
        0.5,
        1.0,
    ]


@pytest.mark.req("R-5.3-3")
@pytest.mark.parametrize(
    ("index_type", "trigger", "exit"),
    [
        ("rainfall_below", 100.0, 120.0),  # exit above the trigger
        ("rainfall_below", 100.0, 100.0),  # exit equal to the trigger
        ("dry_spell_above", 10.0, 5.0),  # exit below the trigger
        ("dry_spell_above", 10.0, 10.0),  # exit equal to the trigger
        ("rainfall_below", float("nan"), 40.0),
        ("rainfall_below", 100.0, float("-inf")),
        ("dry_spell_above", 10.0, float("inf")),
    ],
)
def test_exit_not_on_the_paying_side_is_rejected(
    index_type: IndexType, trigger: float, exit: float
) -> None:
    with pytest.raises(InvalidCoverError):
        validate_index(index_type, trigger, exit)
    with pytest.raises(InvalidCoverError):
        validate_cover(index_type, trigger, exit, LIMIT_CENTS)


@pytest.mark.req("R-5.3-3")
@pytest.mark.parametrize("limit_cents", [0, -1])
def test_limit_that_is_not_positive_is_rejected(limit_cents: int) -> None:
    with pytest.raises(InvalidCoverError):
        validate_cover("rainfall_below", 100.0, 40.0, limit_cents)


@pytest.mark.req("R-5.3-3")
def test_valid_covers_are_accepted() -> None:
    validate_cover("rainfall_below", 100.0, 40.0, LIMIT_CENTS)
    validate_cover("dry_spell_above", 10.0, 25.0, 1)
