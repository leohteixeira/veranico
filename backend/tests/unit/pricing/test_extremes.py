"""Extreme seasons (SPEC 9.4, contracts section 4): hand-ordered seasons."""

import pytest

from veranico.modules.pricing.domain.extremes import extreme_seasons
from veranico.modules.pricing.domain.index import IndexType
from veranico.modules.pricing.domain.rounding import to_tenth

SEASONS = [2000, 2001, 2002, 2003, 2004]


@pytest.mark.req("R-9.4-5")
def test_rainfall_below_ranks_the_lowest_totals_first() -> None:
    values = [120.0, 45.5, 300.0, 80.0, 210.0]

    worst = extreme_seasons("rainfall_below", SEASONS, values, 3)

    assert [(item.rank, item.season, item.index_value) for item in worst] == [
        (1, 2001, 45.5),
        (2, 2003, 80.0),
        (3, 2000, 120.0),
    ]


@pytest.mark.req("R-9.4-5")
def test_dry_spell_above_ranks_the_longest_spells_first() -> None:
    values = [12.0, 30.0, 7.0, 21.0, 9.0]

    worst = extreme_seasons("dry_spell_above", SEASONS, values, 3)

    assert [(item.rank, item.season, item.index_value) for item in worst] == [
        (1, 2001, 30.0),
        (2, 2003, 21.0),
        (3, 2000, 12.0),
    ]


@pytest.mark.req("R-9.4-5")
def test_return_period_is_seasons_plus_one_over_the_rank() -> None:
    seasons = list(range(1950, 2025))  # 75 seasons
    values = [float(100 + position) for position in range(75)]

    worst = extreme_seasons("rainfall_below", seasons, values, 3)

    assert worst[0].return_period_years == 76.0
    assert worst[1].return_period_years == 38.0
    assert to_tenth(worst[2].return_period_years) == 25.3


@pytest.mark.req("R-9.4-5")
def test_five_seasons_give_return_periods_of_six_three_and_two_years() -> None:
    worst = extreme_seasons("rainfall_below", SEASONS, [5.0, 4.0, 3.0, 2.0, 1.0], 3)

    assert [item.return_period_years for item in worst] == [6.0, 3.0, 2.0]


@pytest.mark.req("R-9.4-5")
@pytest.mark.parametrize("index_type", ["rainfall_below", "dry_spell_above"])
def test_tie_keeps_the_earlier_season_first(index_type: IndexType) -> None:
    # every season ties: the order is by season for either direction
    worst = extreme_seasons(index_type, [2003, 2001, 2002], [50.0, 50.0, 50.0], 3)

    assert [(item.rank, item.season) for item in worst] == [(1, 2001), (2, 2002), (3, 2003)]


@pytest.mark.req("R-9.4-5")
def test_tie_for_the_worst_value_is_ordered_by_season() -> None:
    worst = extreme_seasons("dry_spell_above", SEASONS, [10.0, 25.0, 8.0, 25.0, 3.0], 2)

    assert [(item.rank, item.season) for item in worst] == [(1, 2001), (2, 2003)]


@pytest.mark.req("R-9.4-5")
def test_top_n_larger_than_the_number_of_seasons_returns_them_all() -> None:
    worst = extreme_seasons("rainfall_below", SEASONS, [120.0, 45.5, 300.0, 80.0, 210.0], 10)

    assert [item.season for item in worst] == [2001, 2003, 2000, 2004, 2002]
    assert [item.rank for item in worst] == [1, 2, 3, 4, 5]


def test_top_n_below_one_and_mismatched_lengths_are_programming_errors() -> None:
    with pytest.raises(ValueError, match="top_n"):
        extreme_seasons("rainfall_below", SEASONS, [1.0] * 5, 0)
    with pytest.raises(ValueError, match="one index value"):
        extreme_seasons("rainfall_below", SEASONS, [1.0], 1)
