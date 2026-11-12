"""Do a cube cell and a point series tell the same story? (SPEC 4.4)

The check compares the cube of a region with the point series of a place inside it. They
are two different products (ADR 0017): the cube is ERA5-Land on the 0.1 degree grid, read
from Google Earth Engine (ADR 0019), the point series is ERA5 on the 0.25 degree grid from
Open-Meteo.
Before 2019 they also cut the day one hour apart in the summers with daylight saving time
(ADR 0018). So the two never agree exactly, and the check is a tolerance, not an equality.
What it must catch is a mistake in the pipeline: a wrong unit, days shifted by one, a
wrong cell.

TOLERANCES, set once at human gate H1 (2026-11-11) from the first comparison of the real
cubes with fresh Open-Meteo series, 1950 to 2025 (27,759 common days), at one place per
region (the places of the tests):

    region           mean abs daily diff   share of days > 1 mm   relative total diff
    sul-de-minas     1.438 mm              0.297                  0.083
    sorriso          1.501 mm              0.310                  0.051
    ribeirao-preto   1.264 mm              0.225                  0.025

Rule, per metric: the worst of the three regions plus a margin of 20%, rounded to the
nearest 0.1 mm and the nearest 0.01. The margin absorbs a revision of either product and
the years added later; it is not adjusted afterwards to make a run pass.

What the limits still catch, measured on the same real series:

* a factor of 1000 either way (values left in metres, or converted twice): relative total
  difference 2.00 in every region, twenty times the limit;
* days shifted by one, either way: 3.28 to 3.64 mm a day, against 1.8;
* the wrong region (the cube cell of another region's place): 2.78 to 4.41 mm a day.

What they cannot catch is the neighbouring cell. The point series is ERA5 on the 0.25 degree
grid, wider than two cube cells, so the eight neighbours of the right cell differ from it by
1.16 to 1.83 mm a day, some less than the right cell itself. Every cell within one of the
right cell passes; only from three to seven cells away (by region) does every cell fail.
Cell indexing is proven instead without the second product: by the recorded consistency
test, whose test cube holds another place's series in every other cell, by the cell
geometry tests of `regions.py`, and by the request grid tests of the download step (pixel
centres are the cell centres, ADR 0019).
"""

from dataclasses import dataclass

import numpy as np

# Largest mean absolute difference between the two daily values, in millimetres:
# 1.501 (Sorriso) plus 20%.
MAX_MEAN_ABS_DAILY_DIFF_MM = 1.8
# Largest difference between the two totals over the overlap, relative to their mean:
# 0.083 (Sul de Minas) plus 20%.
MAX_RELATIVE_TOTAL_DIFF = 0.10

# The share of days in the report counts differences above this.
NOTABLE_DAILY_DIFF_MM = 1.0


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    overlap_days: int  # days present, with a value, in both series
    mean_abs_daily_diff_mm: float
    share_of_days_over_1mm: float  # share of the overlap days that differ by more than 1 mm
    relative_total_diff: float  # |total a - total b| over the mean of the two totals


def compare_series(
    dates_a: np.ndarray,
    precipitation_a: np.ndarray,
    dates_b: np.ndarray,
    precipitation_b: np.ndarray,
) -> ConsistencyReport:
    """Compare two daily series over the days both have a value for.

    Dates are datetime64[D], each series without duplicates; the two need not start or end
    together. Without any common day the differences are reported as infinite, so the
    report is never within tolerance.
    """
    _, in_a, in_b = np.intersect1d(
        dates_a.astype("datetime64[D]"), dates_b.astype("datetime64[D]"), return_indices=True
    )
    a, b = precipitation_a[in_a], precipitation_b[in_b]
    valued = ~(np.isnan(a) | np.isnan(b))
    a, b = a[valued], b[valued]
    if a.size == 0:
        return ConsistencyReport(0, float("inf"), 1.0, float("inf"))
    difference = np.abs(a - b)
    total_a, total_b = float(a.sum()), float(b.sum())
    mean_total = (total_a + total_b) / 2
    return ConsistencyReport(
        overlap_days=int(a.size),
        mean_abs_daily_diff_mm=float(difference.mean()),
        share_of_days_over_1mm=float((difference > NOTABLE_DAILY_DIFF_MM).mean()),
        relative_total_diff=0.0 if mean_total == 0 else abs(total_a - total_b) / mean_total,
    )


def within_tolerance(report: ConsistencyReport) -> bool:
    return (
        report.overlap_days > 0
        and report.mean_abs_daily_diff_mm <= MAX_MEAN_ABS_DAILY_DIFF_MM
        and report.relative_total_diff <= MAX_RELATIVE_TOTAL_DIFF
    )
