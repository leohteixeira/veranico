"""Per-cell metrics of a regional cube (SPEC 5.8), for the map.

The cube is `precipitation[time, row, col]`, row 0 on the northern edge; every result keeps
the two cell axes in that order. The only Python loop is over seasons: each season's window
is reduced over days and cells at once by the same functions the single-series path uses.

A cell with a missing (NaN) day in a season has no value for that season (NaN here); its
figures use its own usable seasons. NaN in a result grid means "no value" and leaves the
module as `None`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from veranico.modules.pricing.domain.backtest import paying
from veranico.modules.pricing.domain.index import IndexType, window_index
from veranico.modules.pricing.domain.seasons import WindowBounds, season_slices

Metric = Literal["trigger_frequency", "season_anomaly"]

FREQUENCY_CLASSES = 5  # equal classes between the grid minimum and maximum
ANOMALY_CLASSES = 6  # equal classes symmetric around zero


@dataclass(frozen=True, slots=True)
class CellIndex:
    seasons: tuple[int, ...]  # seasons whose window is wholly inside the cube's dates
    values: npt.NDArray[np.float64]  # [season, row, col]; NaN where the cell has a missing day
    excluded: tuple[int, ...]


def cell_index(
    dates: npt.NDArray[np.datetime64],
    cube_precipitation: npt.NDArray[np.float64],
    index_type: IndexType,
    window: WindowBounds,
) -> CellIndex:
    """The index of every cell for every season of the window."""
    slices = season_slices(dates, window)
    values = np.empty((len(slices.seasons), *cube_precipitation.shape[1:]), dtype=np.float64)
    for position, (start, stop) in enumerate(zip(slices.starts, slices.stops, strict=True)):
        block = cube_precipitation[start:stop]
        season_values = window_index(block, index_type)
        season_values[np.isnan(block).any(axis=0)] = np.nan
        values[position] = season_values
    return CellIndex(slices.seasons, values, slices.excluded)


def trigger_frequency(
    values: npt.NDArray[np.float64], index_type: IndexType, trigger: float
) -> npt.NDArray[np.float64]:
    """Share of each cell's usable seasons in which it would have paid; NaN with none usable."""
    seasons_paying = np.count_nonzero(paying(index_type, values, trigger), axis=0)
    seasons_usable = np.count_nonzero(~np.isnan(values), axis=0)
    frequency = np.full(values.shape[1:], np.nan, dtype=np.float64)
    np.divide(seasons_paying, seasons_usable, out=frequency, where=seasons_usable > 0)
    return frequency


def cell_median(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Each cell's median index over its own usable seasons; NaN for a cell with none."""
    usable = ~np.isnan(values)
    has_seasons = usable.any(axis=0)
    # A cell with no usable season is filled before the reduction, then set back to NaN.
    median = np.nanmedian(np.where(has_seasons, values, 0.0), axis=0)
    return np.asarray(np.where(has_seasons, median, np.nan), dtype=np.float64)


def season_anomaly(
    values: npt.NDArray[np.float64], season_position: int
) -> npt.NDArray[np.float64]:
    """`(value - median) / median` of one season per cell; NaN where the median is zero or
    the cell has no value in that season."""
    median = cell_median(values)
    season_values = values[season_position]
    anomaly = np.full(median.shape, np.nan, dtype=np.float64)
    defined = ~np.isnan(season_values) & ~np.isnan(median) & (median != 0)
    np.divide(season_values - median, median, out=anomaly, where=defined)
    return anomaly


def class_breaks(metric: Metric, values: npt.NDArray[np.float64]) -> list[float]:
    """Class boundaries of the legend, both ends included.

    `trigger_frequency`: five equal classes from the grid minimum to its maximum.
    `season_anomaly`: six equal classes symmetric around zero, out to the largest magnitude.
    When every cell has the same value the breaks collapse to that value twice; a grid with
    no value has no breaks.
    """
    present = values[~np.isnan(values)]
    if present.size == 0:
        return []
    low, high = float(present.min()), float(present.max())
    if low == high:
        return [low, high]
    if metric == "trigger_frequency":
        return [float(edge) for edge in np.linspace(low, high, FREQUENCY_CLASSES + 1)]
    reach = max(abs(low), abs(high))
    return [float(edge) for edge in np.linspace(-reach, reach, ANOMALY_CLASSES + 1)]


def cells_paying(
    values: npt.NDArray[np.float64], season_position: int, index_type: IndexType, trigger: float
) -> int:
    """Number of cells that would have paid in one season; a cell without a value does not."""
    return int(np.count_nonzero(paying(index_type, values[season_position], trigger)))


def suggested_season(seasons: Sequence[int], values: npt.NDArray[np.float64]) -> int | None:
    """The season most evenly split between cells below and above their own median.

    A cell at its median, or without a value, is neither. Ties go to the season with the
    most classified cells, then to the most recent. `None` when there is no season.
    """
    if len(seasons) == 0:
        return None
    median = cell_median(values)
    cell_axes = tuple(range(1, values.ndim))
    below = np.count_nonzero(values < median, axis=cell_axes)
    above = np.count_nonzero(values > median, axis=cell_axes)
    difference = np.abs(below - above)
    classified = below + above
    best = min(
        range(len(seasons)),
        key=lambda position: (difference[position], -classified[position], -seasons[position]),
    )
    return int(seasons[best])
