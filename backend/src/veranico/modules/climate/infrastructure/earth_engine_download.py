"""The download step of the cube build: hourly ERA5-Land from Google Earth Engine, turned
into one yearly file of local-day sums (ADR 0019, which replaces the source of ADR 0018).

This is the only file that imports `ee` (the `earthengine-api` client), and it does so
inside one function, so nothing here is loaded by the running service.

What is asked, per region and year, in one `computePixels` call. The collection
`ECMWF/ERA5_LAND/HOURLY`, band `total_precipitation` (metres, accumulated from the start of
the day's forecast and reset at midnight), the images whose `hour` property is 0 or k,
where k is the region's fixed standard offset behind UTC (ADR 0018), from 01:00 UTC on
1 January to k:00 UTC on 1 January of the next year. The value stamped 00:00 is the total
of the previous UTC day (the catalogue builds its daily sums from "the first hour's data of
the following day"), so the total of the local day D is, as in ADR 0018,

    tp(D+1, 00:00) - tp(D, k:00) + tp(D+1, k:00)

That is 731 or 733 bands of 20 by 20 pixels: under the documented limits of a
`computePixels` request (1024 bands, 48 MB uncompressed). The pixel grid is requested
explicitly: EPSG:4326, 0.1 degree pixels whose top-left corner is the region's north-west
corner, so pixel centres are the region's cell centres. The native grid of the collection
is checked first: its pixel centres must be the same 0.1 degree points, or nothing is
fetched, so no request can resample.

NOT VERIFIED against a real answer (human gate H1 is open): that `system:time_start` is
the end of the accumulation (the validity time), the band order of `toBands` and the
native projection. Each is checked on the answer: the time steps against the expected
list, the band names against the image ids, the projection against the grid, and a
negative local-day total (which a wrong time convention produces) fails. A mismatch raises
`EarthEngineResponseError` naming what was found: the step never writes a yearly file from
an answer it does not recognise.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import Grid, RegionDef, cell_centre
from veranico.modules.climate.infrastructure.yearly_file import write_yearly_file

COLLECTION = "ECMWF/ERA5_LAND/HOURLY"
BAND = "total_precipitation"
HOUR_PROPERTY = "hour"
CRS = "EPSG:4326"
STEP_DEG = 0.1
# The documented limit of one `computePixels` request.
MAX_BANDS = 1024
# The client reads no environment variable for the project (ADR 0019), so this is ours.
PROJECT_VARIABLE = "EARTHENGINE_PROJECT"
AUTHENTICATE_COMMAND = "cd backend && uv run --group cube earthengine authenticate"
# A grid coordinate counts as a multiple of 0.1 degree within this, in degrees.
GRID_TOLERANCE_DEG = 1e-6

# Hours behind UTC, the standard offset, used for every year (ADR 0018): Brasilia time for
# Minas Gerais and Sao Paulo, Amazon time for Mato Grosso.
UTC_OFFSET_HOURS: Mapping[str, int] = {"sul-de-minas": 3, "ribeirao-preto": 3, "sorriso": 4}

# The difference of two accumulations stored as 32-bit floats can come out a hair below
# zero on a dry day. A value between minus this and zero is taken as zero; anything lower
# is not rounding and fails. One micrometre of water. Provisional until the first real
# answer shows the size of the noise (H1).
ROUNDING_NOISE_M = 1e-6


class EarthEngineResponseError(WeatherDataError):
    """The answer of Earth Engine is not what the download step asked for."""


class EarthEngineSetupError(Exception):
    """No project or no stored credentials: the owner has a step to take first."""


class EarthEngineUnreachableError(Exception):
    """No answer was obtained from Earth Engine (no network)."""


class EarthEngineRefusedError(Exception):
    """Earth Engine answered with an error (project not registered, API not enabled...)."""


@dataclass(frozen=True, slots=True)
class YearRequest:
    """One `computePixels` request: the images of a region and year at the two steps."""

    collection: str
    band: str
    hours: tuple[int, int]
    start: datetime  # inclusive, UTC
    end: datetime  # exclusive, UTC
    grid: dict[str, Any]  # the PixelGrid of the request

    def expected_steps(self) -> np.ndarray:
        """The UTC time steps the answer must hold, in order."""
        first = np.datetime64(self.start.replace(tzinfo=None), "h")
        last = np.datetime64(self.end.replace(tzinfo=None), "h")
        hours = np.arange(first, last, dtype="datetime64[h]")
        of_day = (hours - hours.astype("datetime64[D]")).astype(np.int64)
        steps: np.ndarray = hours[np.isin(of_day, self.hours)]
        return steps


@dataclass(frozen=True, slots=True)
class Answer:
    """What Earth Engine returned for a `YearRequest`."""

    native_crs: str
    native_transform: Sequence[float]  # scaleX, shearX, translateX, shearY, scaleY, translateY
    image_ids: Sequence[str]  # `system:index` of each image, in the order of the bands
    time_starts_ms: Sequence[int]  # `system:time_start` of each image, same order
    pixels: np.ndarray  # structured array (height, width), one field per band


# Runs one request. Blocks. Raises the errors above, never a client exception.
Fetch = Callable[[YearRequest], Answer]


def offset_hours(region: RegionDef) -> int:
    try:
        return UTC_OFFSET_HOURS[region.region_id]
    except KeyError:
        raise WeatherDataError(f"no UTC offset is defined for {region.region_id}") from None


def pixel_grid(region: Grid) -> dict[str, Any]:
    """The region's grid as an Earth Engine PixelGrid: pixel (0, 0) has its top-left corner
    at the region's north-west corner, so its centre is the centre of cell (0, 0)."""
    return {
        "crsCode": CRS,
        "affineTransform": {
            "scaleX": region.step_deg,
            "shearX": 0,
            "translateX": region.west,
            "shearY": 0,
            "scaleY": -region.step_deg,
            "translateY": region.north,
        },
        "dimensions": {"width": region.nx, "height": region.ny},
    }


def year_request(region: RegionDef, year: int) -> YearRequest:
    """From 01:00 UTC on 1 January (the first step after midnight; 00:00 belongs to the year
    before) to k:00 UTC on 1 January of the next year, which closes 31 December."""
    offset = offset_hours(region)
    request = YearRequest(
        collection=COLLECTION,
        band=BAND,
        hours=(0, offset),
        start=datetime(year, 1, 1, 1, tzinfo=UTC),
        end=datetime(year + 1, 1, 1, offset + 1, tzinfo=UTC),
        grid=pixel_grid(region),
    )
    bands = len(request.expected_steps())
    if bands > MAX_BANDS:  # cannot happen for one year; a guard for a changed request
        raise WeatherDataError(f"{bands} bands exceed the {MAX_BANDS} of one request")
    return request


def local_day_totals(
    stamps: np.ndarray, tp: np.ndarray, year: int, offset: int
) -> tuple[np.ndarray, np.ndarray]:
    """Local-day totals of `year` from the two daily time steps.

    `stamps` are the UTC time steps of `tp` (first axis), in any order: 00:00 of every day
    from 2 January to 1 January of the next year, and `offset`:00 of every day from
    1 January to 1 January of the next year. Returns (the days as datetime64[D], the totals
    in the unit of `tp`), computed as

        total(D) = tp(D+1, 00:00) - tp(D, offset:00) + tp(D+1, offset:00)

    Raises `EarthEngineResponseError` when a time step is missing, repeated or unexpected,
    or when a total is negative beyond rounding noise.
    """
    hours = stamps.astype("datetime64[h]")
    if (hours.astype(stamps.dtype) != stamps).any():
        raise EarthEngineResponseError("the time steps are not whole hours")
    days = np.arange(f"{year:04d}-01-01", f"{year + 1:04d}-01-02", dtype="datetime64[D]")
    midnight = days.astype("datetime64[h]")[1:]  # 00:00 of D+1 for every day D
    shifted = days.astype("datetime64[h]") + np.timedelta64(offset, "h")
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
        raise EarthEngineResponseError(f"wrong time steps for {year}; " + "; ".join(problems))

    position = {step: index for index, step in enumerate(hours.tolist())}
    at_midnight = tp[[position[step] for step in midnight.tolist()]]
    at_offset = tp[[position[step] for step in shifted.tolist()]]
    totals = at_midnight - at_offset[:-1] + at_offset[1:]
    lowest = np.nanmin(totals) if np.isfinite(totals).any() else 0.0
    if lowest < -ROUNDING_NOISE_M:
        raise EarthEngineResponseError(
            f"a local-day total of {year} is negative ({lowest} m): the accumulation rule "
            "assumed for total precipitation does not hold for this answer"
        )
    cleaned: np.ndarray = np.where(totals < 0, 0.0, totals)
    return days[:-1], cleaned


def check_native_grid(crs: str, transform: Sequence[float]) -> None:
    """Refuse a native grid whose pixel centres are not the 0.1 degree points of ours."""
    if crs != CRS or len(transform) != 6:
        raise EarthEngineResponseError(
            f"the native projection is {crs} {list(transform)}, expected {CRS} with 0.1 degree "
            "pixels"
        )
    scale_x, shear_x, translate_x, shear_y, scale_y, translate_y = transform

    def on_grid(value: float) -> bool:
        steps = value / STEP_DEG
        return bool(abs(steps - np.rint(steps)) * STEP_DEG <= GRID_TOLERANCE_DEG)

    if not (
        math.isclose(scale_x, STEP_DEG, abs_tol=GRID_TOLERANCE_DEG)
        and math.isclose(scale_y, -STEP_DEG, abs_tol=GRID_TOLERANCE_DEG)
        and shear_x == 0
        and shear_y == 0
        and on_grid(translate_x + scale_x / 2)
        and on_grid(translate_y + scale_y / 2)
    ):
        raise EarthEngineResponseError(
            f"the native grid {list(transform)} does not put pixel centres on multiples of "
            "0.1 degree: reading the region's cells from it would resample"
        )


def answer_to_metres(request: YearRequest, answer: Answer) -> tuple[np.ndarray, np.ndarray]:
    """(time steps as datetime64[h], `tp` in metres of shape (steps, ny, nx)) of an answer,
    after every check of the answer against the request."""
    check_native_grid(answer.native_crs, answer.native_transform)
    if len(answer.image_ids) != len(answer.time_starts_ms):
        raise EarthEngineResponseError(
            f"{len(answer.image_ids)} image ids for {len(answer.time_starts_ms)} time steps"
        )
    names = answer.pixels.dtype.names or ()
    expected_names = [f"{image_id}_{request.band}" for image_id in answer.image_ids]
    if list(names) != expected_names:
        raise EarthEngineResponseError(
            f"the bands {list(names)[:3]}... are not the images {expected_names[:3]}... in order"
        )
    dimensions = request.grid["dimensions"]
    shape = (dimensions["height"], dimensions["width"])
    if answer.pixels.shape != shape:
        raise EarthEngineResponseError(
            f"the pixels have shape {answer.pixels.shape}, the grid {shape}"
        )
    stamps = np.array(answer.time_starts_ms, dtype="datetime64[ms]")
    expected = request.expected_steps()
    if (
        not np.array_equal(np.sort(stamps.astype("datetime64[h]")), expected)
        or (stamps.astype("datetime64[h]").astype("datetime64[ms]") != stamps).any()
    ):
        raise EarthEngineResponseError(
            f"the time steps {stamps[:2]}... are not the {len(expected)} expected from "
            f"{expected[0]} to {expected[-1]}"
        )
    metres = np.stack([answer.pixels[name].astype(np.float64) for name in names])
    return stamps.astype("datetime64[h]"), metres


class EarthEngineYearlySource:
    """`YearlySource` over Earth Engine."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch

    def provenance(self, region: RegionDef) -> dict[str, str]:
        offset = offset_hours(region)
        transform = pixel_grid(region)["affineTransform"]
        return {
            "service": "Google Earth Engine, computePixels",
            "collection": COLLECTION,
            "band": BAND,
            "hours_utc": f"00:00,{offset:02d}:00",
            "grid": (
                f"{CRS}, {region.nx}x{region.ny} pixels of {region.step_deg} degree from "
                f"west {transform['translateX']}, north {transform['translateY']}"
            ),
            "requests": "one per year",
            "local_day": (
                f"tp(D+1, 00:00) - tp(D, {offset:02d}:00) + tp(D+1, {offset:02d}:00), "
                f"UTC-{offset} (ADR 0018, ADR 0019)"
            ),
        }

    def download(self, region: RegionDef, year: int, target: Path) -> None:
        request = year_request(region, year)
        stamps, metres = answer_to_metres(request, self._fetch(request))
        days, totals = local_day_totals(stamps, metres, year, offset_hours(region))
        latitudes = np.array([cell_centre(region, row, 0)[0] for row in range(region.ny)])
        longitudes = np.array([cell_centre(region, 0, col)[1] for col in range(region.nx)])
        write_yearly_file(
            target,
            days,
            latitudes,
            longitudes,
            totals,
            {"source": "era5-land", "year": str(year), **self.provenance(region)},
        )


def earth_engine_fetch(project: str) -> Fetch:
    """Initialise the client with the stored credentials and return a `Fetch` over it.

    Called before any download, so a missing login or an unknown project fails at once.
    Raises `EarthEngineSetupError` without credentials, `EarthEngineRefusedError` when
    Earth Engine refuses the project, `EarthEngineUnreachableError` without network.
    """
    import ee
    import httplib2
    from google.auth import exceptions as auth_errors

    def run[T](step: Callable[[], T]) -> T:
        try:
            return step()
        except auth_errors.RefreshError:
            raise EarthEngineSetupError(
                "the stored Earth Engine credentials were refused: run "
                f"`{AUTHENTICATE_COMMAND} --force`"
            ) from None
        except (OSError, httplib2.HttpLib2Error, auth_errors.TransportError) as error:
            raise EarthEngineUnreachableError("no answer from Earth Engine") from error
        except ee.EEException as error:
            message = str(error).splitlines()[0] if str(error) else type(error).__name__
            raise EarthEngineRefusedError(f"Earth Engine refused the request: {message}") from None

    try:
        ee.data.get_persistent_credentials()
    except ee.EEException:
        raise EarthEngineSetupError(
            f"no Earth Engine credentials are stored: run `{AUTHENTICATE_COMMAND}` once"
        ) from None
    run(lambda: ee.Initialize(project=project))

    def fetch(request: YearRequest) -> Answer:
        collection = (
            ee.ImageCollection(request.collection)
            .filterDate(_milliseconds(request.start), _milliseconds(request.end))
            .filter(ee.Filter.inList(leftField=HOUR_PROPERTY, rightValue=list(request.hours)))
            .select(request.band)
            .sort("system:time_start")
        )
        info: dict[str, Any] | None = run(
            lambda: ee.Dictionary(
                {
                    "ids": collection.aggregate_array("system:index"),
                    "times": collection.aggregate_array("system:time_start"),
                    "projection": collection.first().projection(),
                }
            ).getInfo()
        )
        if not info or not isinstance(info.get("projection"), dict):
            raise EarthEngineResponseError(f"no image of {request.collection} in the request")
        pixels = run(
            lambda: ee.data.computePixels(
                {
                    "expression": collection.toBands(),
                    "fileFormat": "NUMPY_NDARRAY",
                    "grid": request.grid,
                }
            )
        )
        projection = info["projection"]
        return Answer(
            native_crs=projection.get("crs", ""),
            native_transform=projection.get("transform", []),
            image_ids=info["ids"],
            time_starts_ms=info["times"],
            pixels=pixels,
        )

    return fetch


def _milliseconds(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)
