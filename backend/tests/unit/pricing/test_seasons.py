"""Windows and seasons (SPEC 5.1): hand-built date ranges, no weather values needed."""

import numpy as np
import pytest

from veranico.modules.pricing.domain.errors import InvalidCoverError
from veranico.modules.pricing.domain.seasons import parse_window, season_slices


def days(first: str, last: str) -> np.ndarray:
    """Every day from `first` to `last`, both included."""
    stop = np.datetime64(last, "D") + np.timedelta64(1, "D")
    return np.arange(np.datetime64(first, "D"), stop, dtype="datetime64[D]")


def day(text: str) -> np.datetime64:
    return np.datetime64(text, "D")


@pytest.mark.req("R-5.1-1")
def test_window_bounds_are_month_and_day() -> None:
    window = parse_window("09-01", "10-31")

    assert (window.start_month, window.start_day) == (9, 1)
    assert (window.end_month, window.end_day) == (10, 31)
    assert not window.crosses_year


@pytest.mark.req("R-5.1-1")
def test_window_with_end_before_start_crosses_the_year() -> None:
    assert parse_window("11-15", "02-15").crosses_year
    assert not parse_window("03-10", "03-10").crosses_year


@pytest.mark.req("R-5.1-1")
@pytest.mark.parametrize("bound", ["02-29", "13-01", "02-30", "00-10", "9-1", "0901", "ab-cd", ""])
def test_bound_that_is_not_a_real_month_and_day_is_rejected(bound: str) -> None:
    with pytest.raises(InvalidCoverError):
        parse_window(bound, "10-31")
    with pytest.raises(InvalidCoverError):
        parse_window("09-01", bound)


@pytest.mark.req("R-5.1-1")
def test_same_year_window_runs_from_first_to_last_day_inclusive() -> None:
    dates = days("2000-01-01", "2001-12-31")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (2000, 2001)
    assert slices.excluded == ()
    for start, stop, year in zip(slices.starts, slices.stops, slices.seasons, strict=True):
        assert stop - start == 61
        assert dates[start] == day(f"{year}-09-01")
        assert dates[stop - 1] == day(f"{year}-10-31")


@pytest.mark.req("R-5.1-1")
@pytest.mark.req("R-5.1-2")
def test_crossing_window_ends_in_the_next_year_and_keeps_the_start_year() -> None:
    dates = days("2000-01-01", "2001-12-31")

    slices = season_slices(dates, parse_window("11-15", "02-15"))

    assert slices.seasons == (2000,)
    (start,), (stop,) = slices.starts, slices.stops
    assert dates[start] == day("2000-11-15")
    assert dates[stop - 1] == day("2001-02-15")
    assert stop - start == 93


@pytest.mark.req("R-5.1-3")
def test_crossing_seasons_cut_by_either_end_of_the_series_are_excluded() -> None:
    dates = days("2000-01-01", "2001-12-31")

    slices = season_slices(dates, parse_window("11-15", "02-15"))

    # 1999 ends inside the series (2000-02-15) and 2001 starts inside it: both touch it.
    assert slices.excluded == (1999, 2001)


@pytest.mark.req("R-5.1-3")
def test_series_starting_on_new_year_excludes_no_same_year_season() -> None:
    dates = days("1950-01-01", "1951-12-31")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (1950, 1951)
    assert slices.excluded == ()


@pytest.mark.req("R-5.1-3")
def test_series_ending_on_new_years_eve_excludes_the_last_crossing_season() -> None:
    dates = days("2023-01-01", "2024-12-31")

    slices = season_slices(dates, parse_window("11-15", "02-15"))

    assert slices.seasons == (2023,)
    assert 2024 in slices.excluded


@pytest.mark.req("R-5.1-1")
def test_leap_day_inside_a_window_is_counted_when_it_exists() -> None:
    dates = days("2000-01-01", "2001-12-31")

    slices = season_slices(dates, parse_window("02-01", "03-31"))

    lengths = dict(
        zip(
            slices.seasons,
            (b - a for a, b in zip(slices.starts, slices.stops, strict=True)),
            strict=True,
        )
    )
    assert lengths == {2000: 60, 2001: 59}
    assert dates[slices.stops[0] - 1] == day("2000-03-31")
    assert dates[slices.starts[1]] == day("2001-02-01")


@pytest.mark.req("R-5.1-1")
def test_start_equal_to_end_is_a_one_day_window() -> None:
    dates = days("2000-01-01", "2000-12-31")

    slices = season_slices(dates, parse_window("03-10", "03-10"))

    assert slices.seasons == (2000,)
    assert slices.stops[0] - slices.starts[0] == 1
    assert dates[slices.starts[0]] == day("2000-03-10")


@pytest.mark.req("R-5.1-3")
def test_missing_value_inside_a_window_excludes_that_season_only() -> None:
    dates = days("2000-01-01", "2002-12-31")
    missing = np.zeros(len(dates), dtype=bool)
    missing[dates == day("2001-10-31")] = True  # the last day of the 2001 window

    slices = season_slices(dates, parse_window("09-01", "10-31"), missing)

    assert slices.seasons == (2000, 2002)
    assert slices.excluded == (2001,)


@pytest.mark.req("R-5.1-3")
def test_missing_value_on_the_first_day_of_a_window_excludes_the_season() -> None:
    dates = days("2000-01-01", "2001-12-31")
    missing = dates == day("2000-09-01")

    slices = season_slices(dates, parse_window("09-01", "10-31"), missing)

    assert slices.seasons == (2001,)
    assert slices.excluded == (2000,)


@pytest.mark.req("R-5.1-3")
def test_missing_values_next_to_a_window_exclude_nothing() -> None:
    dates = days("2000-01-01", "2001-12-31")
    missing = (dates == day("2000-08-31")) | (dates == day("2000-11-01"))

    slices = season_slices(dates, parse_window("09-01", "10-31"), missing)

    assert slices.seasons == (2000, 2001)
    assert slices.excluded == ()


@pytest.mark.req("R-5.1-3")
def test_season_whose_window_starts_before_the_series_is_excluded() -> None:
    dates = days("2000-09-02", "2001-12-31")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (2001,)
    assert slices.excluded == (2000,)


@pytest.mark.req("R-5.1-3")
def test_season_whose_window_ends_after_the_series_is_excluded() -> None:
    dates = days("2000-01-01", "2001-10-30")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (2000,)
    assert slices.excluded == (2001,)


@pytest.mark.req("R-5.1-3")
def test_series_covering_exactly_one_window_gives_one_usable_season() -> None:
    dates = days("2000-09-01", "2000-10-31")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (2000,)
    assert (slices.starts, slices.stops) == ((0,), (61,))
    assert slices.excluded == ()


@pytest.mark.req("R-5.1-3")
def test_season_that_does_not_touch_the_series_is_not_reported() -> None:
    dates = days("2000-01-01", "2000-06-30")

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == ()
    assert slices.excluded == ()


@pytest.mark.req("R-5.1-3")
def test_gap_in_the_dates_inside_a_window_excludes_that_season() -> None:
    dates = days("2000-01-01", "2001-12-31")
    dates = dates[dates != day("2001-09-15")]

    slices = season_slices(dates, parse_window("09-01", "10-31"))

    assert slices.seasons == (2000,)
    assert slices.excluded == (2001,)


def test_empty_series_has_no_season() -> None:
    slices = season_slices(np.array([], dtype="datetime64[D]"), parse_window("09-01", "10-31"))

    assert slices.seasons == ()
    assert slices.excluded == ()


def test_missing_mask_of_another_length_is_a_programming_error() -> None:
    dates = days("2000-01-01", "2000-12-31")

    with pytest.raises(ValueError, match="missing"):
        season_slices(dates, parse_window("09-01", "10-31"), np.zeros(3, dtype=bool))
