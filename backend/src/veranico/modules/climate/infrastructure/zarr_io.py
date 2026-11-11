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
from zarr.abc.store import Store

# Where a store lives: a local directory, or a Zarr store object (Cloud Storage).
Location = Path | Store

ZARR_FORMAT = 3
TIME = "time"
PRECIPITATION = "precipitation_mm"
LAT = "lat"
LON = "lon"
CELL_CHUNK = 10  # cells per chunk along each side of a cube


def write_series(target: Location, dates: np.ndarray, precipitation_mm: np.ndarray) -> None:
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


def write_cube(
    target: Location,
    dates: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    precipitation_mm: np.ndarray,
    *,
    chunks: tuple[int, int, int] | None = None,
) -> None:
    """Write a cube of shape (days, ny, nx) as a new store.

    Chunks: the whole time axis by at most 10 by 10 cells, so the series of one cell is one
    chunk object and the whole cube is a handful (ADR 0016, measured on the real cubes).
    `chunks` exists for that measurement only.
    """
    days, ny, nx = precipitation_mm.shape
    dataset = xr.Dataset(
        {PRECIPITATION: ((TIME, LAT, LON), precipitation_mm.astype(np.float64))},
        coords={
            TIME: dates.astype("datetime64[ns]"),
            LAT: latitudes.astype(np.float64),
            LON: longitudes.astype(np.float64),
        },
    )
    dataset.to_zarr(
        target,
        mode="w-",
        consolidated=False,
        zarr_format=ZARR_FORMAT,
        encoding={
            PRECIPITATION: {"chunks": chunks or cube_chunks(days, ny, nx)},
            TIME: {"chunks": (days,)},
        },
    )


def cube_chunks(days: int, ny: int, nx: int) -> tuple[int, int, int]:
    return (days, min(CELL_CHUNK, ny), min(CELL_CHUNK, nx))


def read_cube(source: Location) -> tuple[np.ndarray, np.ndarray]:
    """Return (dates as datetime64[D], precipitation in mm as float64 (days, ny, nx))."""
    with xr.open_zarr(source, consolidated=False, zarr_format=ZARR_FORMAT, chunks=None) as dataset:
        dates = dataset[TIME].to_numpy().astype("datetime64[D]")
        # No second copy: the array is stored as float64, and a cube is 89 MB.
        precipitation = dataset[PRECIPITATION].to_numpy().astype(np.float64, copy=False)
    return dates, precipitation


def read_cell(source: Location, row: int, col: int) -> tuple[np.ndarray, np.ndarray]:
    """The series of one cell of a cube; only the chunk that holds the cell is read."""
    with xr.open_zarr(source, consolidated=False, zarr_format=ZARR_FORMAT, chunks=None) as dataset:
        dates = dataset[TIME].to_numpy().astype("datetime64[D]")
        cell = dataset[PRECIPITATION].isel({LAT: row, LON: col})
        precipitation = cell.to_numpy().astype(np.float64)
    return dates, precipitation


def read_series(source: Location) -> tuple[np.ndarray, np.ndarray]:
    """Return (dates as datetime64[D], precipitation in mm as float64) of a one-cell store."""
    with xr.open_zarr(source, consolidated=False, zarr_format=ZARR_FORMAT, chunks=None) as dataset:
        dates = dataset[TIME].to_numpy().astype("datetime64[D]")
        precipitation = dataset[PRECIPITATION].to_numpy().astype(np.float64)
    return dates, precipitation
