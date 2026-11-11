"""Rules a daily series must satisfy before it is written (SPEC 4.4)."""

import numpy as np

from veranico.modules.climate.domain.errors import WeatherDataError


def validate_daily(dates: np.ndarray, precipitation_mm: np.ndarray) -> int:
    """Check one daily series and return its number of missing (NaN) values.

    Raises `WeatherDataError` on unequal lengths, an empty series, a duplicate date, dates
    out of order, a gap or a negative value. Missing values are allowed: the source has
    days without data, and the caller reports them.
    """
    if dates.ndim != 1 or precipitation_mm.shape != dates.shape:
        raise WeatherDataError(
            f"unequal length: dates {dates.shape}, precipitation {precipitation_mm.shape}"
        )
    if dates.size == 0:
        raise WeatherDataError("empty series")
    steps = np.diff(dates.astype("datetime64[D]")).astype(np.int64)
    if (steps == 0).any():
        raise WeatherDataError(f"duplicate date: {_first(dates, steps == 0)}")
    if (steps < 0).any():
        raise WeatherDataError(f"dates out of order at {_first(dates, steps < 0)}")
    if (steps > 1).any():
        raise WeatherDataError(f"gap before {_first(dates, steps > 1)}")
    negative = precipitation_mm < 0  # NaN compares false
    if negative.any():
        raise WeatherDataError(f"negative precipitation on {dates[np.argmax(negative)]}")
    return int(np.isnan(precipitation_mm).sum())


def _first(dates: np.ndarray, breaks: np.ndarray) -> np.datetime64:
    """The date that ends the first offending step."""
    found: np.datetime64 = dates[int(np.argmax(breaks)) + 1]
    return found
