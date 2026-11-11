"""Index value per season (SPEC 5.2).

`rainfall_below`: total precipitation in the window, in millimetres.
`dry_spell_above`: the longest run of consecutive days under 1 mm, counted inside the
window only, in days.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from veranico.modules.pricing.domain.seasons import WindowBounds, season_slices

IndexType = Literal["rainfall_below", "dry_spell_above"]

DRY_DAY_MM = 1.0  # a day is dry when its precipitation is strictly under this


@dataclass(frozen=True, slots=True)
class SeasonIndex:
    seasons: tuple[int, ...]  # usable seasons, ascending start years
    values: npt.NDArray[np.float64]  # one index value per usable season
    excluded: tuple[int, ...]


def index_series(
    dates: npt.NDArray[np.datetime64],
    precipitation_mm: npt.NDArray[np.float64],
    index_type: IndexType,
    window: WindowBounds,
) -> SeasonIndex:
    """The index of every usable season of one daily series; a NaN day is a missing day."""
    slices = season_slices(dates, window, np.isnan(precipitation_mm))
    values = np.array(
        [
            float(window_index(precipitation_mm[start:stop], index_type))
            for start, stop in zip(slices.starts, slices.stops, strict=True)
        ],
        dtype=np.float64,
    )
    return SeasonIndex(slices.seasons, values, slices.excluded)


def window_index(
    window_mm: npt.NDArray[np.float64], index_type: IndexType
) -> npt.NDArray[np.float64]:
    """The index of one window. Days run along axis 0; any further axes (cells) are kept."""
    if index_type == "rainfall_below":
        return np.asarray(window_mm.sum(axis=0), dtype=np.float64)
    return longest_dry_run(window_mm).astype(np.float64)


def longest_dry_run(window_mm: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """Longest run of consecutive dry days along axis 0: a count that resets on a wet day."""
    dry = window_mm < DRY_DAY_MM
    run = np.zeros(dry.shape[1:], dtype=np.int64)
    longest = np.zeros(dry.shape[1:], dtype=np.int64)
    for dry_today in dry:
        run = np.where(dry_today, run + 1, 0)
        longest = np.maximum(longest, run)
    return longest
