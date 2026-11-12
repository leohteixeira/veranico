"""Index values per season (SPEC 5.2), on short series written by hand."""

from collections.abc import Sequence

import numpy as np
import pytest

from veranico.modules.pricing.domain.index import index_series, longest_dry_run
from veranico.modules.pricing.domain.seasons import parse_window

WET = 20.0  # background rain outside the window, so a leak into the index is visible


def january(window_values: Sequence[float], *, outside: float = WET) -> tuple[np.ndarray, ...]:
    """January 2000 with `window_values` written from the 11th on and `outside` elsewhere."""
    dates = np.arange("2000-01-01", "2000-02-01", dtype="datetime64[D]")
    rain = np.full(len(dates), outside, dtype=np.float64)
    rain[10 : 10 + len(window_values)] = window_values
    return dates, rain


def window_for(values: Sequence[float]) -> tuple[str, str]:
    return "01-11", f"01-{10 + len(values):02d}"


def dry_spell(values: Sequence[float], *, outside: float = WET) -> float:
    dates, rain = january(values, outside=outside)
    result = index_series(dates, rain, "dry_spell_above", parse_window(*window_for(values)))
    assert result.seasons == (2000,)
    return float(result.values[0])


@pytest.mark.req("R-5.2-1")
def test_rainfall_index_is_the_total_of_the_window() -> None:
    values = [0.0, 5.5, 12.0, 0.0, 3.2, 0.3, 20.0, 1.0, 0.0, 8.0]  # hand total: 50.0
    dates, rain = january(values)

    result = index_series(dates, rain, "rainfall_below", parse_window("01-11", "01-20"))

    assert result.seasons == (2000,)
    assert result.excluded == ()
    assert result.values.dtype == np.float64
    assert result.values[0] == pytest.approx(50.0, abs=1e-9)


@pytest.mark.req("R-5.2-1")
def test_rainfall_index_of_a_one_day_window_is_that_day() -> None:
    dates, rain = january([7.5])

    result = index_series(dates, rain, "rainfall_below", parse_window("01-11", "01-11"))

    assert result.values.tolist() == [7.5]


@pytest.mark.req("R-5.2-1")
def test_rainfall_index_per_season_over_a_crossing_window() -> None:
    dates = np.arange("2000-01-01", "2003-01-01", dtype="datetime64[D]")
    rain = np.zeros(len(dates), dtype=np.float64)
    rain[dates == np.datetime64("2000-12-31")] = 10.0
    rain[dates == np.datetime64("2001-01-01")] = 4.0
    rain[dates == np.datetime64("2001-01-03")] = 100.0  # the day after the window
    rain[dates == np.datetime64("2001-12-30")] = 2.5
    rain[dates == np.datetime64("2001-12-29")] = 100.0  # the day before the window

    result = index_series(dates, rain, "rainfall_below", parse_window("12-30", "01-02"))

    assert result.seasons == (2000, 2001)
    assert result.values.tolist() == [14.0, 2.5]
    assert result.excluded == (1999, 2002)


@pytest.mark.req("R-5.2-2")
def test_dry_spell_is_the_longest_run_not_the_number_of_dry_days() -> None:
    # runs of 2, 4 and 3 dry days: nine dry days, the longest run is four
    values = [0.0, 0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 6.0]

    assert dry_spell(values) == 4.0


@pytest.mark.req("R-5.2-2")
def test_day_of_exactly_one_millimetre_breaks_a_run() -> None:
    assert dry_spell([0.0, 0.0, 1.0, 0.0, 0.0]) == 2.0


@pytest.mark.req("R-5.2-2")
def test_day_just_under_one_millimetre_does_not_break_a_run() -> None:
    assert dry_spell([0.0, 0.0, 0.9, 0.0, 0.0]) == 5.0


@pytest.mark.req("R-5.2-2")
def test_dry_run_that_starts_before_the_window_counts_only_its_days_inside() -> None:
    # everything outside the window is dry; inside, three dry days then rain
    assert dry_spell([0.0, 0.0, 0.0, 8.0, 8.0, 8.0], outside=0.0) == 3.0


@pytest.mark.req("R-5.2-2")
def test_dry_run_that_continues_after_the_window_counts_only_its_days_inside() -> None:
    assert dry_spell([8.0, 8.0, 8.0, 8.0, 0.0, 0.0], outside=0.0) == 2.0


@pytest.mark.req("R-5.2-2")
def test_all_wet_window_has_no_dry_spell() -> None:
    assert dry_spell([1.0, 2.0, 3.0, 4.0, 5.0], outside=0.0) == 0.0


@pytest.mark.req("R-5.2-2")
def test_all_dry_window_is_one_run_of_its_length() -> None:
    assert dry_spell([0.0] * 7) == 7.0


@pytest.mark.req("R-5.2-2")
def test_longest_dry_run_keeps_the_cell_axes() -> None:
    # two cells side by side, days down the rows
    window = np.array([[0.0, 3.0], [0.0, 0.0], [2.0, 0.0], [0.0, 0.0]])

    assert longest_dry_run(window).tolist() == [2, 3]


@pytest.mark.req("R-5.1-3")
def test_season_with_a_missing_day_has_no_index_and_is_reported() -> None:
    dates = np.arange("2000-01-01", "2002-01-01", dtype="datetime64[D]")
    rain = np.ones(len(dates), dtype=np.float64)
    rain[dates == np.datetime64("2000-01-15")] = np.nan

    result = index_series(dates, rain, "rainfall_below", parse_window("01-11", "01-20"))

    assert result.seasons == (2001,)
    assert result.values.tolist() == [10.0]
    assert result.excluded == (2000,)
