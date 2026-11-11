"""Evidence as NetCDF bytes, written in memory with h5netcdf through xarray.

Checked on xarray 2026.9.0 with h5netcdf 1.8.2: `Dataset.to_netcdf(engine="h5netcdf")`
without a target returns the file as a `memoryview`, and dataset `attrs` become the global
attributes. h5netcdf writes through `h5py`, which must be installed. The same input gives
the same bytes.
"""

from collections.abc import Mapping

import numpy as np
import xarray as xr

TIME = "time"
PRECIPITATION = "precipitation_mm"


def encode_evidence(
    dates: np.ndarray, precipitation_mm: np.ndarray, attributes: Mapping[str, str]
) -> bytes:
    """One variable, `precipitation_mm` over `time`; `attributes` are the global attributes."""
    dataset = xr.Dataset(
        {
            PRECIPITATION: (
                (TIME,),
                precipitation_mm.astype(np.float64),
                {"units": "mm", "long_name": "daily precipitation sum"},
            )
        },
        coords={TIME: dates.astype("datetime64[ns]")},
        attrs=dict(attributes),
    )
    return bytes(dataset.to_netcdf(engine="h5netcdf"))
