"""Reading and writing weather arrays as Zarr stores through xarray.

Checked against xarray 2026.9.0 and zarr 3.4.2: the format is requested explicitly
(Zarr format 3), chunks are set per variable through `encoding`, and `mode="w-"` refuses to
write into an existing store. A Zarr store is a directory of many files and its write is
not atomic, so callers write a new build under a new name and switch a manifest afterwards.
Metadata is not consolidated: a store here holds two arrays, and consolidated metadata is
one more object that could disagree with them.

These functions block; the adapters call them through `asyncio.to_thread`.
"""

from pathlib import Path

import numpy as np
import xarray as xr

ZARR_FORMAT = 3
TIME = "time"
PRECIPITATION = "precipitation_mm"


def write_series(target: Path, dates: np.ndarray, precipitation_mm: np.ndarray) -> None:
    """Write one daily series as a new one-cell store; the whole series is one chunk."""
    days = len(dates)
    dataset = xr.Dataset(
        {PRECIPITATION: ((TIME,), precipitation_mm.astype(np.float64))},
        coords={TIME: dates.astype("datetime64[ns]")},
    )
    dataset.to_zarr(
        target,
        mode="w-",
        consolidated=False,
        zarr_format=ZARR_FORMAT,
        encoding={PRECIPITATION: {"chunks": (days,)}, TIME: {"chunks": (days,)}},
    )


def read_series(source: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (dates as datetime64[D], precipitation in mm as float64) of a one-cell store."""
    with xr.open_zarr(source, consolidated=False, zarr_format=ZARR_FORMAT, chunks=None) as dataset:
        dates = dataset[TIME].to_numpy().astype("datetime64[D]")
        precipitation = dataset[PRECIPITATION].to_numpy().astype(np.float64)
    return dates, precipitation
