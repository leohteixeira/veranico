"""The download step of the cube build: hourly ERA5-Land from the Climate Data Store,
turned into one yearly file of local-day sums (ADR 0018).

This is the only file that imports `cdsapi`, and it does so inside one function, so
nothing here is loaded by the running service.

What is asked. Dataset `reanalysis-era5-land`, variable `total_precipitation` (`tp`,
metres), the region's grid points, two time steps a day: 00:00 UTC and k:00 UTC, where k is
the region's fixed standard offset behind UTC. `tp` is accumulated from 00 UTC, and the
value stamped 00:00 is the total of the previous UTC day, so the total of the local day D is

    tp(D+1, 00:00) - tp(D, k:00) + tp(D+1, k:00)

The last day of a year needs the first day of the next one. A CDS request is a product of
years, months, days and times, so that one day is a second, small request.

NOT VERIFIED against a real answer (human gate H1 is open, there is no account): the
request keys and values below, the names inside the returned file (`tp`, `valid_time`,
`latitude`, `longitude`), the unit attribute and any request size limit. Everything read
from the answer is checked, and a mismatch raises `CdsResponseError` naming what was found:
the step never writes a yearly file from an answer it does not recognise.
"""

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import RegionDef, cell_centre
from veranico.modules.climate.infrastructure.cube_build import matching
from veranico.modules.climate.infrastructure.yearly_file import write_yearly_file

CDS_URL = "https://cds.climate.copernicus.eu/api"
DATASET = "reanalysis-era5-land"
VARIABLE = "total_precipitation"
SHORT_NAME = "tp"
UNITS = "m"
TIME = "valid_time"
LATITUDE = "latitude"
LONGITUDE = "longitude"

# Hours behind UTC, the standard offset, used for every year (ADR 0018): Brasilia time for
# Minas Gerais and Sao Paulo, Amazon time for Mato Grosso.
UTC_OFFSET_HOURS: Mapping[str, int] = {"sul-de-minas": 3, "ribeirao-preto": 3, "sorriso": 4}

# The difference of two accumulations stored as 32-bit floats can come out a hair below
# zero on a dry day. A value between minus this and zero is taken as zero; anything lower
# is not rounding and fails. One micrometre of water. Provisional until the first real
# answer shows the size of the noise (H1).
ROUNDING_NOISE_M = 1e-6

# Downloads one request to a file. Blocks.
Retrieve = Callable[[str, Mapping[str, Any], Path], None]


class CdsResponseError(WeatherDataError):
    """The answer of the Climate Data Store is not what the download step asked for."""


class CdsUnreachableError(Exception):
    """No answer was obtained from the Climate Data Store (no network)."""


def year_request(region: RegionDef, year: int) -> dict[str, Any]:
    """The request for every day of `year` at the two time steps."""
    return {
        **_common(region),
        "year": [f"{year:04d}"],
        "month": [f"{month:02d}" for month in range(1, 13)],
        "day": [f"{day:02d}" for day in range(1, 32)],
    }


def next_day_request(region: RegionDef, year: int) -> dict[str, Any]:
    """The request for 1 January of the next year, which closes 31 December."""
    return {**_common(region), "year": [f"{year + 1:04d}"], "month": ["01"], "day": ["01"]}


def _common(region: RegionDef) -> dict[str, Any]:
    north, west = cell_centre(region, 0, 0)
    south, east = cell_centre(region, region.ny - 1, region.nx - 1)
    return {
        "variable": [VARIABLE],
        "time": ["00:00", f"{offset_hours(region):02d}:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [north, west, south, east],  # the outermost grid points: N, W, S, E
    }


def offset_hours(region: RegionDef) -> int:
    try:
        return UTC_OFFSET_HOURS[region.region_id]
    except KeyError:
        raise WeatherDataError(f"no UTC offset is defined for {region.region_id}") from None


def local_day_totals(
    stamps: np.ndarray, tp: np.ndarray, year: int, offset: int
) -> tuple[np.ndarray, np.ndarray]:
    """Local-day totals of `year` from the two daily time steps.

    `stamps` are the UTC time steps of `tp` (first axis), in any order: for every day of
    the year and for 1 January of the next one, 00:00 and `offset`:00. Returns (the days
    as datetime64[D], the totals in the unit of `tp`), computed as

        total(D) = tp(D+1, 00:00) - tp(D, offset:00) + tp(D+1, offset:00)

    Raises `CdsResponseError` when a time step is missing, repeated or unexpected, or when
    a total is negative beyond rounding noise.
    """
    hours = stamps.astype("datetime64[h]")
    if (hours.astype(stamps.dtype) != stamps).any():
        raise CdsResponseError("the time steps are not whole hours")
    days = np.arange(f"{year:04d}-01-01", f"{year + 1:04d}-01-02", dtype="datetime64[D]")
    midnight = days.astype("datetime64[h]")
    shifted = midnight + np.timedelta64(offset, "h")
    expected = np.concatenate([midnight, shifted])
    found, counts = np.unique(hours, return_counts=True)
    problems = [
        f"{label}: {', '.join(str(step) for step in steps[:5])}"
        for label, steps in (
            ("missing", np.setdiff1d(expected, found)),
            ("unexpected", np.setdiff1d(found, expected)),
            ("repeated", found[counts > 1]),
        )
        if steps.size
    ]
    if problems:
        raise CdsResponseError(f"wrong time steps for {year}; " + "; ".join(problems))

    position = {step: index for index, step in enumerate(hours.tolist())}
    at_midnight = tp[[position[step] for step in midnight.tolist()]]
    at_offset = tp[[position[step] for step in shifted.tolist()]]
    totals = at_midnight[1:] - at_offset[:-1] + at_offset[1:]
    lowest = np.nanmin(totals) if np.isfinite(totals).any() else 0.0
    if lowest < -ROUNDING_NOISE_M:
        raise CdsResponseError(
            f"a local-day total of {year} is negative ({lowest} m): the accumulation rule "
            "assumed for total precipitation does not hold for this answer"
        )
    cleaned: np.ndarray = np.where(totals < 0, 0.0, totals)
    return days[:-1], cleaned


class CdsYearlySource:
    """`YearlySource` over the Climate Data Store."""

    def __init__(self, retrieve: Retrieve) -> None:
        self._retrieve = retrieve

    def provenance(self, region: RegionDef) -> dict[str, str]:
        common = _common(region)
        offset = offset_hours(region)
        return {
            "url": CDS_URL,
            "dataset": DATASET,
            "variable": VARIABLE,
            "time": ",".join(common["time"]),
            "area": ",".join(str(edge) for edge in common["area"]),
            "data_format": common["data_format"],
            "requests": "one per year, plus 1 January of the next year",
            "local_day": (
                f"tp(D+1, 00:00) - tp(D, {offset:02d}:00) + tp(D+1, {offset:02d}:00), "
                f"UTC-{offset} (ADR 0018)"
            ),
        }

    def download(self, region: RegionDef, year: int, target: Path) -> None:
        offset = offset_hours(region)
        latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
        longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
        with tempfile.TemporaryDirectory(dir=target.parent, prefix="cds-") as scratch:
            answers = []
            for name, request in (
                ("year.nc", year_request(region, year)),
                ("next-day.nc", next_day_request(region, year)),
            ):
                path = Path(scratch) / name
                self._retrieve(DATASET, request, path)
                answers.append(_read_answer(path, latitudes, longitudes))
        stamps = np.concatenate([stamps for stamps, _ in answers])
        tp = np.concatenate([values for _, values in answers])
        days, totals = local_day_totals(stamps, tp, year, offset)
        write_yearly_file(
            target,
            days,
            latitudes,
            longitudes,
            totals,
            {"source": "era5-land/cds", "year": str(year), **self.provenance(region)},
        )


def cdsapi_retrieve(key: str) -> Retrieve:
    """A `Retrieve` over the official client. The client is imported on first use."""
    clients: list[Any] = []

    def retrieve(dataset: str, request: Mapping[str, Any], target: Path) -> None:
        import cdsapi
        import requests

        try:
            if not clients:
                clients.append(cdsapi.Client(url=CDS_URL, key=key))
            clients[0].retrieve(dataset, dict(request), str(target))
        except requests.exceptions.ConnectionError as error:
            raise CdsUnreachableError("no answer from the Climate Data Store") from error

    return retrieve


def _read_answer(
    path: Path, latitudes: np.ndarray, longitudes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(time steps, `tp` in metres on the region's grid points) of one downloaded file."""
    try:
        dataset = xr.open_dataset(path, engine="h5netcdf")
    except Exception as error:
        raise CdsResponseError(f"the answer is not a NetCDF file: {error}") from error
    with dataset:
        if SHORT_NAME not in dataset.data_vars:
            raise CdsResponseError(
                f"no variable '{SHORT_NAME}' in the answer, "
                f"found {sorted(map(str, dataset.data_vars))}"
            )
        variable = dataset[SHORT_NAME]
        wanted = (TIME, LATITUDE, LONGITUDE)
        if set(variable.dims) != set(wanted):
            raise CdsResponseError(
                f"'{SHORT_NAME}' has dimensions {variable.dims}, expected {wanted}"
            )
        units = variable.attrs.get("units")
        if units != UNITS:
            raise CdsResponseError(f"'{SHORT_NAME}' is in {units!r}, expected {UNITS!r}")
        stamps = dataset[TIME].to_numpy()
        if not np.issubdtype(stamps.dtype, np.datetime64):
            raise CdsResponseError(f"'{TIME}' is not a time coordinate ({stamps.dtype})")
        try:
            rows = matching(path, LATITUDE, dataset[LATITUDE].to_numpy(), latitudes)
            columns = matching(path, LONGITUDE, dataset[LONGITUDE].to_numpy(), longitudes)
        except WeatherDataError as error:
            raise CdsResponseError(f"the answer does not cover the region: {error}") from None
        metres = variable.transpose(*wanted).to_numpy().astype(np.float64)
    return stamps, metres[:, rows][:, :, columns]
