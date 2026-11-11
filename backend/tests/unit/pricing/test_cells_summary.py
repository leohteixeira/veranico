"""Legend breaks, paying cells and the suggested season (SPEC 5.8 and 12.2 item 4)."""

import numpy as np
import pytest

from tests.unit.pricing import cells_fixture as fixture
from veranico.modules.pricing.domain.cells import (
    Metric,
    cell_index,
    cells_paying,
    class_breaks,
    season_anomaly,
    suggested_season,
    trigger_frequency,
)
from veranico.modules.pricing.domain.index import IndexType
from veranico.modules.pricing.domain.seasons import parse_window

WINDOW = parse_window(*fixture.WINDOW)
NAN = float("nan")


def values_for(index_type: IndexType) -> np.ndarray:
    dates, rain = fixture.cube()
    return cell_index(dates, rain, index_type, WINDOW).values


@pytest.mark.req("R-5.8-3")
def test_frequency_breaks_are_five_equal_classes_from_minimum_to_maximum() -> None:
    # rainfall below 35 mm: frequencies 0.75, 1, 0.25 and 2/3; classes of 0.15 from 0.25 to 1
    rainfall = trigger_frequency(values_for("rainfall_below"), "rainfall_below", 35.0)
    # dry spells above 2 days: 0.25, 1, 0 and 1/3; classes of 0.2 from 0 to 1
    dry_spell = trigger_frequency(values_for("dry_spell_above"), "dry_spell_above", 2.0)

    assert class_breaks("trigger_frequency", rainfall) == pytest.approx(
        [0.25, 0.4, 0.55, 0.7, 0.85, 1.0]
    )
    assert class_breaks("trigger_frequency", dry_spell) == pytest.approx(
        [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )


@pytest.mark.req("R-5.8-3")
def test_anomaly_breaks_are_six_classes_symmetric_around_zero() -> None:
    # season 2003: anomalies -0.2, none, -0.328 and -0.5; the largest magnitude is 0.5
    anomaly = season_anomaly(values_for("rainfall_below"), fixture.SEASONS.index(2003))

    breaks = class_breaks("season_anomaly", anomaly)

    assert breaks == pytest.approx([-0.5, -1 / 3, -1 / 6, 0.0, 1 / 6, 1 / 3, 0.5])


@pytest.mark.req("R-5.8-3")
def test_anomaly_breaks_reach_the_largest_magnitude_on_either_side() -> None:
    # season 2004: anomalies -0.4, none, -0.2 and +1.0
    anomaly = season_anomaly(values_for("rainfall_below"), fixture.SEASONS.index(2004))

    assert class_breaks("season_anomaly", anomaly) == pytest.approx(
        [-1.0, -2 / 3, -1 / 3, 0.0, 1 / 3, 2 / 3, 1.0]
    )


@pytest.mark.req("R-5.8-3")
@pytest.mark.parametrize("metric", ["trigger_frequency", "season_anomaly"])
def test_breaks_collapse_to_the_value_twice_when_every_cell_is_equal(metric: Metric) -> None:
    grid = np.array([[0.4, 0.4], [NAN, 0.4]])

    assert class_breaks(metric, grid) == [0.4, 0.4]


@pytest.mark.req("R-5.8-3")
def test_grid_without_any_value_has_no_breaks() -> None:
    assert class_breaks("trigger_frequency", np.full((2, 2), NAN)) == []


@pytest.mark.req("R-5.8-4")
def test_cells_paying_counts_the_cells_beyond_the_trigger_in_one_season() -> None:
    values = values_for("rainfall_below")

    # 2003: 20, 0, 33.6 and 10 mm are all under 35 mm
    assert cells_paying(values, fixture.SEASONS.index(2003), "rainfall_below", 35.0) == 4
    # 2001: only B (0 mm) and D (20 mm)
    assert cells_paying(values, fixture.SEASONS.index(2001), "rainfall_below", 35.0) == 2
    # 2002: A (30 mm) and B (0 mm); C has 60 mm and D has no value
    assert cells_paying(values, fixture.SEASONS.index(2002), "rainfall_below", 35.0) == 2


@pytest.mark.req("R-5.8-4")
def test_cells_paying_for_dry_spells() -> None:
    values = values_for("dry_spell_above")

    # 2003: spells of 4, 5, 2 and 3 days against a trigger of 2: C does not pay
    assert cells_paying(values, fixture.SEASONS.index(2003), "dry_spell_above", 2.0) == 3
    # 2001: only B (5 days)
    assert cells_paying(values, fixture.SEASONS.index(2001), "dry_spell_above", 2.0) == 1


def split_values() -> np.ndarray:
    """Six seasons by four cells: 10 + season number below the median, 100 + it above.

    Cells below their own median, per season: 4, 3, 2, 2, 1, 0 (so 0, 1, 2, 2, 3, 4 above).
    """
    below = np.array(
        [
            [1, 1, 1, 1],  # 4-0
            [1, 1, 1, 0],  # 3-1
            [1, 1, 0, 0],  # 2-2
            [0, 0, 1, 1],  # 2-2
            [0, 0, 0, 1],  # 1-3
            [0, 0, 0, 0],  # 0-4
        ],
        dtype=bool,
    )
    season_number = np.arange(6, dtype=np.float64)[:, None]
    return np.where(below, 10.0, 100.0) + season_number


@pytest.mark.req("R-12.2-4")
def test_suggested_season_is_the_most_evenly_split_and_of_two_the_later() -> None:
    seasons = [2000, 2001, 2002, 2003, 2004, 2005]
    values = split_values().reshape(6, 2, 2)

    assert suggested_season(seasons, values) == 2003


@pytest.mark.req("R-12.2-4")
def test_evenly_split_season_with_fewer_classified_cells_loses_to_a_fuller_one() -> None:
    # medians: 50 in each of the four cells
    values = np.array(
        [
            [[10.0, 90.0], [20.0, 80.0]],  # 2000: two below, two above
            [[50.0, 50.0], [50.0, 50.0]],  # 2001: every cell at its median, none classified
            [[90.0, 10.0], [50.0, 50.0]],  # 2002: one below, one above
        ]
    )

    # all three are evenly split; 2000 classifies the most cells and wins over the later two
    assert suggested_season([2000, 2001, 2002], values) == 2000


@pytest.mark.req("R-12.2-4")
def test_cell_without_a_value_is_neither_below_nor_above() -> None:
    # medians: 20, 80, 10 and 10 (the two southern cells have no value in 2000)
    values = np.array(
        [
            [[10.0, 90.0], [NAN, NAN]],  # 2000: one below, one above
            [[20.0, 30.0], [10.0, 10.0]],  # 2001: one below, none above
            [[30.0, 80.0], [10.0, 10.0]],  # 2002: none below, one above
        ]
    )

    assert suggested_season([2000, 2001, 2002], values) == 2000


@pytest.mark.req("R-12.2-4")
def test_no_season_suggests_nothing() -> None:
    assert suggested_season([], np.empty((0, 2, 2))) is None


@pytest.mark.req("R-12.2-4")
def test_suggested_season_on_the_hand_cube() -> None:
    # totals against medians 25, 0, 50, 20:
    # 2001: A above, B at, C above, D at      -> 0 below, 2 above
    # 2002: A above, B at, C above, D missing -> 0 below, 2 above
    # 2003: A below, B at, C below, D below   -> 3 below, 0 above
    # 2004: A below, B above, C below, D above -> 2 below, 2 above
    assert suggested_season(fixture.SEASONS, values_for("rainfall_below")) == 2004
