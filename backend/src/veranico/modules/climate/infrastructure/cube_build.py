"""From yearly NetCDF files to one validated cube on a region's grid (SPEC 4.1, ADR 0018).

The input is the shape described in `yearly_file.py`: one file per year, local-day sums in
metres. Anything else fails here with a message that names the file; nothing is guessed.

These functions block.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import xarray as xr

from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import Grid, cell_centre
from veranico.modules.climate.domain.validation import validate_cube
from veranico.modules.climate.infrastructure import yearly_file, zarr_io

MM_PER_M = 1000.0
# Coordinates in a file may be stored as 32-bit floats: -11.6 comes back as -11.6000004.
# A grid step is 0.1 degree, so a thousandth of a degree cannot confuse two grid points.
COORDINATE_TOLERANCE_DEG = 0.001


def convert_years(paths: Sequence[Path], region: Grid) -> xr.Dataset:
    """Merge the yearly files into one cube on the region's grid, in millimetres.

    The result holds `precipitation_mm` over (`time`, `lat`, `lon`) as float64, row 0 at
    the northern edge whatever the order of the latitudes in the files, every year from the
    first to the last present, and every cell validated. The files may cover more than the
    region; they must cover every one of its grid points.
    """
    if not paths:
        raise WeatherDataError("no yearly file to convert")
    latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
    longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
    parts = sorted(
        (_read_year(path, latitudes, longitudes) for path in paths), key=lambda part: part[0]
    )
    years = [year for year, _, _ in parts]
    repeated = sorted({year for year in years if years.count(year) > 1})
    if repeated:
        raise WeatherDataError(f"more than one file for the year(s) {_listed(repeated)}")
    absent = sorted(set(range(years[0], years[-1] + 1)) - set(years))
    if absent:
        raise WeatherDataError(f"missing year(s) {_listed(absent)}")

    dates = np.concatenate([days for _, days, _ in parts])
    precipitation = np.concatenate([values for _, _, values in parts])
    validate_cube(dates, precipitation)
    return xr.Dataset(
        {zarr_io.PRECIPITATION: ((zarr_io.TIME, zarr_io.LAT, zarr_io.LON), precipitation)},
        coords={
            zarr_io.TIME: dates.astype("datetime64[ns]"),
            zarr_io.LAT: latitudes,
            zarr_io.LON: longitudes,
        },
    )


def convert_to_arrays(paths: Sequence[Path], region: Grid) -> tuple[np.ndarray, np.ndarray]:
    """`convert_years` as (dates as datetime64[D], millimetres of shape (days, ny, nx))."""
    cube = convert_years(paths, region)
    return (
        cube[zarr_io.TIME].to_numpy().astype("datetime64[D]"),
        cube[zarr_io.PRECIPITATION].to_numpy(),
    )


def file_checksum(path: Path) -> str:
    """SHA-256 of a file's bytes, the checksum a manifest records per yearly file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _read_year(
    path: Path, latitudes: np.ndarray, longitudes: np.ndarray
) -> tuple[int, np.ndarray, np.ndarray]:
    """(year, days, millimetres on the wanted grid points) of one yearly file."""
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        if yearly_file.VARIABLE not in dataset.data_vars:
            raise WeatherDataError(
                f"{path.name}: no variable '{yearly_file.VARIABLE}', "
                f"found {sorted(map(str, dataset.data_vars))}"
            )
        variable = dataset[yearly_file.VARIABLE]
        wanted = (yearly_file.TIME, yearly_file.LATITUDE, yearly_file.LONGITUDE)
        if set(variable.dims) != set(wanted):
            raise WeatherDataError(
                f"{path.name}: '{yearly_file.VARIABLE}' has dimensions {variable.dims}, "
                f"expected {wanted}"
            )
        units = variable.attrs.get("units")
        if units != yearly_file.UNITS:
            raise WeatherDataError(
                f"{path.name}: '{yearly_file.VARIABLE}' is in {units!r}, "
                f"expected {yearly_file.UNITS!r}"
            )
        stamps = dataset[yearly_file.TIME].to_numpy().astype("datetime64[ns]")
        rows = matching(path, "latitude", dataset[yearly_file.LATITUDE].to_numpy(), latitudes)
        columns = matching(path, "longitude", dataset[yearly_file.LONGITUDE].to_numpy(), longitudes)
        metres = variable.transpose(*wanted).to_numpy().astype(np.float64)

    days = stamps.astype("datetime64[D]")
    if len(days) == 0:
        raise WeatherDataError(f"{path.name}: no day")
    if (days.astype("datetime64[ns]") != stamps).any():
        raise WeatherDataError(f"{path.name}: the time steps are not whole days")
    year = int(days[0].astype("datetime64[Y]").astype(np.int64)) + 1970
    first, last = np.datetime64(f"{year:04d}-01-01"), np.datetime64(f"{year:04d}-12-31")
    if days[0] != first or days[-1] != last or days.min() < first or days.max() > last:
        raise WeatherDataError(
            f"{path.name}: expected the whole year {year}, found {days[0]} to {days[-1]}"
        )
    return year, days, metres[:, rows][:, :, columns] * MM_PER_M


def matching(path: Path, name: str, found: np.ndarray, wanted: np.ndarray) -> np.ndarray:
    """For every wanted coordinate, the index of the file's coordinate that equals it."""
    distance = np.abs(found.astype(np.float64)[None, :] - wanted[:, None])
    nearest: np.ndarray = distance.argmin(axis=1)
    uncovered = wanted[distance.min(axis=1) > COORDINATE_TOLERANCE_DEG]
    if uncovered.size:
        raise WeatherDataError(
            f"{path.name}: no {name} for the grid point(s) {_listed(uncovered.tolist())}"
        )
    return nearest


def _listed(values: Sequence[float]) -> str:
    return ", ".join(str(value) for value in values)
