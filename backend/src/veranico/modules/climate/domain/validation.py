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


def validate_cube(dates: np.ndarray, precipitation_mm: np.ndarray) -> np.ndarray:
    """Check every cell of a cube of shape (days, ny, nx) with `validate_daily`.

    Returns the number of missing values per cell, shape (ny, nx).
    """
    if precipitation_mm.ndim != 3:
        raise WeatherDataError(f"a cube has three dimensions, not {precipitation_mm.ndim}")
    _, ny, nx = precipitation_mm.shape
    missing = np.zeros((ny, nx), dtype=np.int64)
    for row in range(ny):
        for col in range(nx):
            try:
                missing[row, col] = validate_daily(dates, precipitation_mm[:, row, col])
            except WeatherDataError as error:
                raise WeatherDataError(f"cell ({row}, {col}): {error}") from None
    return missing


def _first(dates: np.ndarray, breaks: np.ndarray) -> np.datetime64:
    """The date that ends the first offending step."""
    found: np.datetime64 = dates[int(np.argmax(breaks)) + 1]
    return found
