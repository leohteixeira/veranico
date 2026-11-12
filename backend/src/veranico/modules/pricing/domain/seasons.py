"""Coverage windows and seasons (SPEC 5.1).

A window is `MM-DD` to `MM-DD`, both days included. When the end is earlier in the calendar
than the start, the window ends in the following year; the season keeps its start year as
label. A season is usable when every day of its window is in the series and none is
missing; every other season whose window touches the series is excluded and reported.
"""

import re
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from veranico.modules.pricing.domain.errors import InvalidCoverError

_BOUND = re.compile(r"\d{2}-\d{2}")
_NON_LEAP_YEAR = 2001  # a bound must exist every year, so 02-29 is not one


@dataclass(frozen=True, slots=True)
class WindowBounds:
    start_month: int
    start_day: int
    end_month: int
    end_day: int

    @property
    def crosses_year(self) -> bool:
        return (self.end_month, self.end_day) < (self.start_month, self.start_day)


@dataclass(frozen=True, slots=True)
class SeasonSlices:
    """Usable seasons in ascending order: `dates[starts[i]:stops[i]]` is season `seasons[i]`."""

    seasons: tuple[int, ...]  # start years
    starts: tuple[int, ...]
    stops: tuple[int, ...]  # exclusive
    excluded: tuple[int, ...]  # start years of the seasons that touch the series, incomplete


def parse_window(start: str, end: str) -> WindowBounds:
    """Raises `invalid_cover` unless both bounds are real `MM-DD` days of every year."""
    start_month, start_day = _parse_bound(start)
    end_month, end_day = _parse_bound(end)
    return WindowBounds(start_month, start_day, end_month, end_day)


def season_slices(
    dates: npt.NDArray[np.datetime64],
    window: WindowBounds,
    missing: npt.NDArray[np.bool_] | None = None,
) -> SeasonSlices:
    """Locate every season of `window` in `dates` (strictly increasing days).

    `missing` marks, per day, a value that is absent; a marked day inside a window excludes
    that season.
    """
    days = np.asarray(dates, dtype="datetime64[D]")
    if missing is not None and missing.shape != days.shape:
        raise ValueError("the missing mask must have one entry per date")
    if days.size == 0:
        return SeasonSlices((), (), (), ())
    series_first, series_last = days[0], days[-1]
    years = days[[0, -1]].astype("datetime64[Y]").astype(np.int64) + 1970

    seasons: list[int] = []
    starts: list[int] = []
    stops: list[int] = []
    excluded: list[int] = []
    # A crossing season that started the year before the series can still end inside it.
    for year in range(int(years[0]) - 1, int(years[1]) + 1):
        end_year = year + 1 if window.crosses_year else year
        window_first = _day(year, window.start_month, window.start_day)
        window_last = _day(end_year, window.end_month, window.end_day)
        if window_last < series_first or window_first > series_last:
            continue  # the season does not touch the series
        label = year
        start = int(np.searchsorted(days, window_first, side="left"))
        stop = int(np.searchsorted(days, window_last, side="right"))
        window_days = int((window_last - window_first) / np.timedelta64(1, "D")) + 1
        usable = stop - start == window_days
        if usable and missing is not None:
            usable = not bool(missing[start:stop].any())
        if usable:
            seasons.append(label)
            starts.append(start)
            stops.append(stop)
        else:
            excluded.append(label)
    return SeasonSlices(tuple(seasons), tuple(starts), tuple(stops), tuple(excluded))


def _parse_bound(text: str) -> tuple[int, int]:
    if _BOUND.fullmatch(text) is None:
        raise InvalidCoverError("a window bound must be written MM-DD")
    month, day = int(text[:2]), int(text[3:])
    try:
        date(_NON_LEAP_YEAR, month, day)
    except ValueError:
        raise InvalidCoverError("a window bound must be a real day of every year") from None
    return month, day


def _day(year: int, month: int, day: int) -> np.datetime64:
    return np.datetime64(f"{year:04d}-{month:02d}-{day:02d}", "D")
