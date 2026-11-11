"""Per-cell metrics (SPEC 5.8) against the hand-computed 2 by 2 grid of `cells_fixture.py`."""

import numpy as np
import pytest

from tests.unit.pricing import cells_fixture as fixture
from veranico.modules.pricing.domain.backtest import backtest
from veranico.modules.pricing.domain.cells import (
    cell_index,
    cell_median,
    season_anomaly,
    trigger_frequency,
)
from veranico.modules.pricing.domain.index import IndexType, index_series
from veranico.modules.pricing.domain.seasons import parse_window

WINDOW = parse_window(*fixture.WINDOW)
RAINFALL_TRIGGER = 35.0  # pays when the total is under 35 mm
DRY_SPELL_TRIGGER = 2.0  # pays when the spell is longer than 2 days


def values_for(index_type: IndexType) -> np.ndarray:
    dates, rain = fixture.cube()
    return cell_index(dates, rain, index_type, WINDOW).values


@pytest.mark.req("R-5.8-1")
@pytest.mark.req("R-5.8-2")
def test_cell_index_gives_the_hand_totals_per_season_and_cell() -> None:
    dates, rain = fixture.cube()

    result = cell_index(dates, rain, "rainfall_below", WINDOW)

    assert result.seasons == fixture.SEASONS
    assert result.excluded == ()
    assert result.values.shape == (4, 2, 2)
    np.testing.assert_allclose(result.values, fixture.RAINFALL_TOTALS, atol=1e-9, equal_nan=True)


@pytest.mark.req("R-5.8-1")
def test_cell_index_gives_the_hand_dry_spells_per_season_and_cell() -> None:
    np.testing.assert_array_equal(values_for("dry_spell_above"), fixture.DRY_SPELLS)


@pytest.mark.req("R-5.8-1")
def test_cell_with_a_missing_day_has_no_value_for_that_season_only() -> None:
    index_types: tuple[IndexType, ...] = ("rainfall_below", "dry_spell_above")
    for index_type in index_types:
        missing = np.isnan(values_for(index_type))
        assert missing.sum() == 1
        assert missing[1, 1, 1]  # season 2002, cell D


@pytest.mark.req("R-5.8-1")
def test_trigger_frequency_of_rainfall_below_35_mm() -> None:
    # A pays in 2002, 2003, 2004; B always; C in 2003 only; D in two of its three seasons
    frequency = trigger_frequency(values_for("rainfall_below"), "rainfall_below", RAINFALL_TRIGGER)

    np.testing.assert_allclose(frequency, [[0.75, 1.0], [0.25, 2 / 3]], atol=1e-12)


@pytest.mark.req("R-5.8-1")
def test_trigger_frequency_of_dry_spells_above_2_days() -> None:
    # A pays in 2003 only (a spell of exactly 2 days does not pay); B always; C never;
    # D in one of its three seasons
    frequency = trigger_frequency(
        values_for("dry_spell_above"), "dry_spell_above", DRY_SPELL_TRIGGER
    )

    np.testing.assert_allclose(frequency, [[0.25, 1.0], [0.0, 1 / 3]], atol=1e-12)


@pytest.mark.req("R-5.8-1")
def test_cell_with_no_usable_season_has_no_frequency() -> None:
    values = np.array([[[10.0, np.nan]], [[50.0, np.nan]]])  # two seasons, one row, two cells

    frequency = trigger_frequency(values, "rainfall_below", 35.0)

    assert frequency[0, 0] == 0.5
    assert np.isnan(frequency[0, 1])


@pytest.mark.req("R-5.8-2")
def test_cell_median_uses_each_cells_own_usable_seasons() -> None:
    median = cell_median(values_for("rainfall_below"))

    # A: 15, 20, 30, 50; B: 0, 0, 0, 8; C: 33.6, 40, 60, 100; D: 10, 20, 40 (2002 is missing)
    np.testing.assert_allclose(median, [[25.0, 0.0], [50.0, 20.0]], atol=1e-9)


@pytest.mark.req("R-5.8-2")
def test_season_anomaly_of_2003_is_the_value_against_the_cells_own_median() -> None:
    anomaly = season_anomaly(values_for("rainfall_below"), fixture.SEASONS.index(2003))

    # A (20 - 25) / 25; C (33.6 - 50) / 50; D (10 - 20) / 20
    assert anomaly[0, 0] == pytest.approx(-0.2)
    assert anomaly[1, 0] == pytest.approx(-0.328)
    assert anomaly[1, 1] == pytest.approx(-0.5)


@pytest.mark.req("R-5.8-2")
def test_cell_with_a_median_of_zero_has_no_anomaly() -> None:
    anomaly = season_anomaly(values_for("rainfall_below"), fixture.SEASONS.index(2004))

    assert np.isnan(anomaly[0, 1])  # B: median 0, although it rained 8 mm in 2004
    # A (15 - 25) / 25; C (40 - 50) / 50; D (40 - 20) / 20
    np.testing.assert_allclose(anomaly, [[-0.4, np.nan], [-0.2, 1.0]], atol=1e-12, equal_nan=True)


@pytest.mark.req("R-5.8-2")
def test_cell_without_a_value_in_the_season_has_no_anomaly() -> None:
    anomaly = season_anomaly(values_for("rainfall_below"), fixture.SEASONS.index(2002))

    # A (30 - 25) / 25; C (60 - 50) / 50; B has a median of zero; D is missing in 2002
    np.testing.assert_allclose(anomaly, [[0.2, np.nan], [0.2, np.nan]], atol=1e-12, equal_nan=True)


@pytest.mark.req("R-5.8-2")
def test_season_anomaly_of_dry_spells() -> None:
    anomaly = season_anomaly(values_for("dry_spell_above"), fixture.SEASONS.index(2003))

    # medians: A 1.5 (0, 1, 2, 4); B 5; C 0.5 (0, 0, 1, 2); D 2 (0, 2, 3)
    # A (4 - 1.5) / 1.5; B (5 - 5) / 5; C (2 - 0.5) / 0.5; D (3 - 2) / 2
    np.testing.assert_allclose(anomaly, [[5 / 3, 0.0], [3.0, 0.5]], atol=1e-12)


@pytest.mark.req("R-5.8-1")
@pytest.mark.req("R-5.8-2")
@pytest.mark.parametrize(
    ("index_type", "trigger", "exit"),
    [("rainfall_below", RAINFALL_TRIGGER, 5.0), ("dry_spell_above", DRY_SPELL_TRIGGER, 5.0)],
)
def test_each_cell_equals_the_single_series_path(
    index_type: IndexType, trigger: float, exit: float
) -> None:
    dates, rain = fixture.cube()
    cells = cell_index(dates, rain, index_type, WINDOW)
    frequency = trigger_frequency(cells.values, index_type, trigger)

    for row in range(2):
        for col in range(2):
            single = index_series(dates, rain[:, row, col], index_type, WINDOW)
            usable = [cells.seasons.index(season) for season in single.seasons]
            np.testing.assert_allclose(cells.values[usable, row, col], single.values, atol=1e-9)
            # the seasons the cell has no value for are the ones the series excludes
            cell_values = cells.values[:, row, col]
            without = {
                season
                for season, value in zip(cells.seasons, cell_values, strict=True)
                if np.isnan(value)
            }
            assert without == set(single.excluded)
            figures = backtest(single, index_type, trigger, exit, 1_000_000, 1)
            assert frequency[row, col] == pytest.approx(figures.trigger_frequency)


@pytest.mark.req("R-5.8-1")
def test_seasons_cut_by_the_cube_dates_are_excluded_for_every_cell() -> None:
    dates, rain = fixture.cube()

    result = cell_index(dates, rain, "rainfall_below", parse_window("12-30", "01-03"))

    assert result.seasons == (2001, 2002, 2003)
    assert result.excluded == (2000, 2004)
    assert result.values.shape == (3, 2, 2)


def test_row_zero_stays_the_northern_edge() -> None:
    dates, rain = fixture.cube()

    result = cell_index(dates, rain, "rainfall_below", WINDOW)

    # season 2001: A and B on row 0, C and D on row 1
    assert result.values[0].tolist() == [[50.0, 0.0], [100.0, 20.0]]
