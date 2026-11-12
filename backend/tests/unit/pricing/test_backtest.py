"""Backtest aggregates and trend (SPEC 5.4), on hand-built seasons with a minimum of four.

Cover used throughout unless stated: rainfall_below, trigger 100 mm, exit 40 mm,
limit R$ 300,000.00 (30,000,000 centavos).
"""

from collections.abc import Sequence

import numpy as np
import pytest

from veranico.modules.pricing.domain.backtest import BacktestFigures, backtest, paying, trend
from veranico.modules.pricing.domain.errors import InsufficientHistoryError, InvalidCoverError
from veranico.modules.pricing.domain.index import IndexType, SeasonIndex

LIMIT_CENTS = 30_000_000
MIN_SEASONS = 4


def season_index(
    values: Sequence[float], *, first: int = 2000, excluded: tuple[int, ...] = ()
) -> SeasonIndex:
    seasons = tuple(range(first, first + len(values)))
    return SeasonIndex(seasons, np.array(values, dtype=np.float64), excluded)


def rainfall(values: Sequence[float], *, excluded: tuple[int, ...] = ()) -> BacktestFigures:
    return backtest(
        season_index(values, excluded=excluded),
        "rainfall_below",
        100.0,
        40.0,
        LIMIT_CENTS,
        MIN_SEASONS,
    )


@pytest.mark.req("R-5.4-1")
def test_each_usable_season_has_its_index_value_and_payout() -> None:
    figures = rainfall([130.0, 110.0, 70.0, 40.0])

    assert figures.seasons == (2000, 2001, 2002, 2003)
    assert figures.index_values.tolist() == [130.0, 110.0, 70.0, 40.0]
    assert figures.payouts.tolist() == pytest.approx([0, 0, 15_000_000, 30_000_000], abs=1e-6)
    assert figures.seasons_used == 4


@pytest.mark.req("R-5.4-2")
def test_aggregates_of_payouts_0_0_15m_30m() -> None:
    figures = rainfall([130.0, 110.0, 70.0, 40.0])

    assert figures.trigger_frequency == 0.5
    assert figures.burn_cost == pytest.approx(11_250_000, abs=1e-6)  # the mean, not the median
    assert figures.max_payout == pytest.approx(30_000_000, abs=1e-6)
    assert figures.max_payout_season == 2003


@pytest.mark.req("R-5.4-2")
def test_dry_spell_cover_aggregates() -> None:
    # trigger 10 days, exit 25: 16 days pays 12,000,000 and 25 days the full limit
    figures = backtest(
        season_index([8.0, 16.0, 25.0, 10.0, 3.0]), "dry_spell_above", 10.0, 25.0, LIMIT_CENTS, 4
    )

    assert figures.payouts.tolist() == pytest.approx([0, 12_000_000, 30_000_000, 0, 0], abs=1e-6)
    assert figures.trigger_frequency == pytest.approx(0.4)
    assert figures.burn_cost == pytest.approx(8_400_000, abs=1e-6)
    assert figures.max_payout_season == 2002


@pytest.mark.req("R-5.4-2")
def test_excluded_seasons_enter_no_denominator() -> None:
    figures = rainfall([130.0, 110.0, 70.0, 40.0], excluded=(1998, 1999, 2004, 2005))

    assert figures.seasons_excluded == (1998, 1999, 2004, 2005)
    assert figures.seasons_used == 4
    assert figures.trigger_frequency == 0.5
    assert figures.burn_cost == pytest.approx(11_250_000, abs=1e-6)


@pytest.mark.req("R-5.4-2")
def test_season_exactly_at_the_trigger_does_not_count_as_paying() -> None:
    figures = rainfall([100.0, 130.0, 70.0, 40.0])

    assert figures.trigger_frequency == 0.5
    assert figures.payouts[0] == 0.0


@pytest.mark.req("R-5.4-2")
@pytest.mark.parametrize(
    ("index_type", "values", "expected"),
    [
        ("rainfall_below", [99.9, 100.0, 100.1], [True, False, False]),
        ("dry_spell_above", [9.0, 10.0, 11.0], [False, False, True]),
    ],
)
def test_paying_means_strictly_beyond_the_trigger(
    index_type: IndexType, values: list[float], expected: list[bool]
) -> None:
    trigger = 100.0 if index_type == "rainfall_below" else 10.0

    assert paying(index_type, values, trigger).tolist() == expected


@pytest.mark.req("R-5.4-2")
def test_maximum_payout_on_a_tie_names_the_earliest_season() -> None:
    figures = rainfall([130.0, 20.0, 70.0, 40.0])

    assert figures.max_payout == pytest.approx(30_000_000, abs=1e-6)
    assert figures.max_payout_season == 2001


@pytest.mark.req("R-5.4-2")
def test_nothing_paid_has_no_maximum_season() -> None:
    figures = rainfall([130.0, 110.0, 120.0, 100.0])

    assert figures.trigger_frequency == 0.0
    assert figures.burn_cost == 0.0
    assert figures.max_payout == 0.0
    assert figures.max_payout_season is None


@pytest.mark.req("R-5.4-3")
@pytest.mark.req("R-5.4-4")
def test_index_rising_ten_per_year_has_a_slope_of_100_per_decade_and_is_significant() -> None:
    figures = rainfall([10.0, 20.0, 30.0, 40.0])

    assert figures.trend.slope_per_decade == pytest.approx(100.0)
    assert figures.trend.p_value < 0.001
    assert figures.trend.significant


@pytest.mark.req("R-5.4-3")
def test_trend_uses_the_season_years_not_their_positions() -> None:
    # seasons 2000, 2002, 2004, 2006 (the odd years were excluded): 10 per two years
    seasons = (2000, 2002, 2004, 2006)

    figures = trend(seasons, np.array([10.0, 20.0, 30.0, 40.0]))

    assert figures.slope_per_decade == pytest.approx(50.0)


@pytest.mark.req("R-5.4-3")
def test_falling_index_has_a_negative_slope() -> None:
    figures = rainfall([40.0, 30.0, 20.0, 10.0])

    assert figures.trend.slope_per_decade == pytest.approx(-100.0)


@pytest.mark.req("R-5.4-3")
@pytest.mark.req("R-5.4-4")
def test_constant_series_has_slope_zero_p_value_one_and_is_not_significant() -> None:
    figures = rainfall([55.0, 55.0, 55.0, 55.0])

    assert figures.trend.slope_per_decade == 0.0
    assert figures.trend.p_value == 1.0
    assert not figures.trend.significant


@pytest.mark.req("R-5.4-4")
def test_p_value_between_five_and_ten_percent_is_not_significant() -> None:
    # Least squares by hand: Sxx = 17.5, Sxy = 8.5, slope 0.485714 per year.
    # Two-sided p-value 0.068876 (t distribution, 4 degrees of freedom; SciPy 1.18.1).
    figures = rainfall([0.0, 2.0, 1.0, 3.0, 2.0, 3.0])

    assert figures.trend.slope_per_decade == pytest.approx(4.857143, abs=1e-6)
    assert figures.trend.p_value == pytest.approx(0.068876, abs=1e-6)
    assert not figures.trend.significant


@pytest.mark.req("R-5.4-4")
def test_p_value_under_five_percent_is_significant() -> None:
    # Sxx = 17.5, Sxy = 11, slope 0.628571 per year; p-value 0.040186 (SciPy 1.18.1).
    figures = rainfall([1.0, 3.0, 2.0, 4.0, 3.0, 5.0])

    assert figures.trend.p_value == pytest.approx(0.040186, abs=1e-6)
    assert figures.trend.significant


def test_three_seasons_under_a_minimum_of_four_is_insufficient_history() -> None:
    with pytest.raises(InsufficientHistoryError):
        rainfall([130.0, 70.0, 40.0])


def test_exactly_the_minimum_number_of_seasons_is_enough() -> None:
    assert rainfall([130.0, 110.0, 70.0, 40.0]).seasons_used == MIN_SEASONS


@pytest.mark.req("R-5.3-3")
def test_backtest_rejects_an_invalid_cover() -> None:
    with pytest.raises(InvalidCoverError):
        backtest(season_index([1.0, 2.0, 3.0, 4.0]), "rainfall_below", 40.0, 100.0, LIMIT_CENTS, 4)
    with pytest.raises(InvalidCoverError):
        backtest(season_index([1.0, 2.0, 3.0, 4.0]), "rainfall_below", 100.0, 40.0, 0, 4)
