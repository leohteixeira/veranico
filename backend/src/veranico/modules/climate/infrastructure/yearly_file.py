"""The yearly NetCDF file the cube converter reads (ADR 0018).

One file per region and year, holding the precipitation of every local day in metres. The
download step writes it from the hourly ERA5-Land answer; the synthetic generator writes
the same shape, so everything after the download runs without a Copernicus account.

Shape: variable `tp` in metres over (`valid_time`, `latitude`, `longitude`). `valid_time`
is the local day; `latitude` and `longitude` are the grid points (cell centres) in degrees.
The names follow the short name ECMWF documents for total precipitation and the coordinate
names of its NetCDF output; the order of the latitudes is not part of the shape, and a
reader must not rely on it.
"""

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import xarray as xr

VARIABLE = "tp"
UNITS = "m"
TIME = "valid_time"
LATITUDE = "latitude"
LONGITUDE = "longitude"


def write_yearly_file(
    target: Path,
    days: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    precipitation_m: np.ndarray,
    attributes: Mapping[str, str],
) -> None:
    """Write one yearly file. `precipitation_m` has shape (days, latitudes, longitudes)."""
    dataset = xr.Dataset(
        {
            VARIABLE: (
                (TIME, LATITUDE, LONGITUDE),
                precipitation_m.astype(np.float64),
                {"units": UNITS, "long_name": "Total precipitation"},
            )
        },
        coords={
            TIME: days.astype("datetime64[ns]"),
            LATITUDE: (LATITUDE, latitudes.astype(np.float64), {"units": "degrees_north"}),
            LONGITUDE: (LONGITUDE, longitudes.astype(np.float64), {"units": "degrees_east"}),
        },
        attrs=dict(attributes),
    )
    dataset.to_netcdf(target, engine="h5netcdf")
