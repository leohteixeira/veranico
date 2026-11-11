"""Which days of a series belong to a coverage window over a range of seasons.

`climate` cannot import `pricing`, so the day rule of SPEC 5.1 is restated here in its
smallest form: a window is `MM-DD` to `MM-DD`, both days included; when the end is earlier
in the calendar than the start the window ends in the following year; a season is labelled
by the year it starts in. A bound must be a day of every year, so `02-29` is not one.
"""

import re
from datetime import date

import numpy as np

from veranico.shared.kernel.errors import InvalidArgumentsError

_BOUND = re.compile(r"\d{2}-\d{2}")
_NON_LEAP_YEAR = 2001


def window_mask(
    dates: np.ndarray, window_start: str, window_end: str, first_season: int, last_season: int
) -> np.ndarray:
    """A boolean mask over `dates`: the window days of the seasons `first_season` to `last_season`.

    Raises `invalid_arguments` for a malformed bound or a reversed range of seasons.
    """
    if first_season > last_season:
        raise InvalidArgumentsError("first_season is later than last_season")
    start, end = _bound(window_start), _bound(window_end)
    crosses_year = end < start
    days = dates.astype("datetime64[D]")
    mask = np.zeros(days.shape, dtype=bool)
    for season in range(first_season, last_season + 1):
        first = np.datetime64(date(season, *start))
        last = np.datetime64(date(season + 1 if crosses_year else season, *end))
        mask |= (days >= first) & (days <= last)
    return mask


def _bound(text: str) -> tuple[int, int]:
    if _BOUND.fullmatch(text) is None:
        raise InvalidArgumentsError("a window bound must be written MM-DD")
    month, day = int(text[:2]), int(text[3:])
    try:
        date(_NON_LEAP_YEAR, month, day)
    except ValueError:
        raise InvalidArgumentsError("a window bound must be a real day of every year") from None
    return month, day
