"""A 2 by 2 cube with four five-day seasons written by hand (window 01-01 to 01-05).

Cell layout, row 0 on the northern edge:

    A (0, 0)   B (0, 1)
    C (1, 0)   D (1, 1)

Rainfall totals in millimetres and longest dry spells in days, per season:

    season   A total/spell   B total/spell   C total/spell   D total/spell
    2001     50 / 0          0 / 5           100 / 0         20 / 0
    2002     30 / 2          0 / 5           60 / 1          missing
    2003     20 / 4          0 / 5           33.6 / 2        10 / 3
    2004     15 / 1          8 / 4           40 / 0          40 / 2

Medians of the totals: A 25, B 0, C 50, D 20 (D over its three usable seasons).

This file is data for the tests, not a test module.
"""

import numpy as np

NAN = float("nan")
SEASONS = (2001, 2002, 2003, 2004)
WINDOW = ("01-01", "01-05")

# DAILY[cell][season] = the five days of the window
DAILY: dict[tuple[int, int], dict[int, list[float]]] = {
    (0, 0): {  # A
        2001: [10.0, 10.0, 10.0, 10.0, 10.0],
        2002: [0.0, 0.0, 10.0, 10.0, 10.0],
        2003: [0.0, 0.0, 0.0, 0.0, 20.0],
        2004: [5.0, 0.0, 5.0, 0.0, 5.0],
    },
    (0, 1): {  # B
        2001: [0.0, 0.0, 0.0, 0.0, 0.0],
        2002: [0.0, 0.0, 0.0, 0.0, 0.0],
        2003: [0.0, 0.0, 0.0, 0.0, 0.0],
        2004: [8.0, 0.0, 0.0, 0.0, 0.0],
    },
    (1, 0): {  # C
        2001: [20.0, 20.0, 20.0, 20.0, 20.0],
        2002: [20.0, 0.0, 20.0, 0.0, 20.0],
        2003: [0.9, 0.9, 30.0, 0.9, 0.9],  # 0.9 mm is a dry day
        2004: [1.0, 1.0, 1.0, 1.0, 36.0],  # 1.0 mm is not
    },
    (1, 1): {  # D
        2001: [4.0, 4.0, 4.0, 4.0, 4.0],
        2002: [0.0, NAN, 0.0, 0.0, 0.0],  # a missing day: no value this season
        2003: [0.0, 0.0, 0.0, 10.0, 0.0],
        2004: [0.0, 20.0, 0.0, 0.0, 20.0],
    },
}

RAINFALL_TOTALS = np.array(
    [
        [[50.0, 0.0], [100.0, 20.0]],
        [[30.0, 0.0], [60.0, NAN]],
        [[20.0, 0.0], [33.6, 10.0]],
        [[15.0, 8.0], [40.0, 40.0]],
    ]
)
DRY_SPELLS = np.array(
    [
        [[0.0, 5.0], [0.0, 0.0]],
        [[2.0, 5.0], [1.0, NAN]],
        [[4.0, 5.0], [2.0, 3.0]],
        [[1.0, 4.0], [0.0, 2.0]],
    ]
)


def cube() -> tuple[np.ndarray, np.ndarray]:
    """Dates 2001-01-01 to 2004-12-31 and the cube; 50 mm falls on every day outside a window."""
    dates = np.arange("2001-01-01", "2005-01-01", dtype="datetime64[D]")
    rain = np.full((len(dates), 2, 2), 50.0, dtype=np.float64)
    for (row, col), by_season in DAILY.items():
        for season, days in by_season.items():
            start = int(np.searchsorted(dates, np.datetime64(f"{season}-01-01")))
            rain[start : start + 5, row, col] = days
    return dates, rain
