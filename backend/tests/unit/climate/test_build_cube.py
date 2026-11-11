"""The cube build: the Earth Engine download step, the yearly cache, the script and its exit
codes. Nothing here needs a network or an account: Earth Engine is a fake."""

import json
import subprocess
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from scripts import build_cube as script

from veranico.modules.climate.application.build_cube import BuildCube, InstallSyntheticCube
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import RegionDef, cell_centre, region_by_id
from veranico.modules.climate.infrastructure import earth_engine_download as download
from veranico.modules.climate.infrastructure.cube_build import convert_to_arrays, file_checksum
from veranico.modules.climate.infrastructure.earth_engine_download import (
    ROUNDING_NOISE_M,
    Answer,
    EarthEngineRefusedError,
    EarthEngineResponseError,
    EarthEngineSetupError,
    EarthEngineUnreachableError,
    EarthEngineYearlySource,
    YearRequest,
    earth_engine_fetch,
    local_day_totals,
    year_request,
)
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.synthetic import (
    GENERATOR,
    generate_cube,
    generator_parameters,
    write_synthetic_year,
)
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import cube_dataset_id

CLOCK = FixedClock(datetime(2026, 11, 11, 12, 0, tzinfo=UTC))
_SORRISO = region_by_id("sorriso")
_SUL_DE_MINAS = region_by_id("sul-de-minas")
assert _SORRISO is not None
assert _SUL_DE_MINAS is not None
SORRISO: RegionDef = _SORRISO  # UTC-4
SUL_DE_MINAS: RegionDef = _SUL_DE_MINAS  # UTC-3
HOUR = np.timedelta64(1, "h")


# The two-step formula of ADR 0018, on a series written by hand.


def two_steps(year: int, offset: int, values: Mapping[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Accumulated `tp` of one cell at 00:00 of every day from 2 January to 1 January of
    the next year and at `offset`:00 of every day from 1 January to 1 January of the next
    year: zero, except the time steps named in `values`."""
    days = np.arange(f"{year}-01-01", f"{year + 1}-01-02", dtype="datetime64[D]")
    midnight = days.astype("datetime64[h]")
    stamps = np.concatenate([midnight[1:], midnight + np.timedelta64(offset, "h")])
    tp = np.zeros((len(stamps), 1, 1))
    for stamp, value in values.items():
        (index,) = np.nonzero(stamps == np.datetime64(stamp, "h"))
        tp[index[0], 0, 0] = value
    return stamps.astype("datetime64[ms]"), tp


def totals_by_day(days: np.ndarray, totals: np.ndarray) -> dict[str, float]:
    return {
        str(day): float(total) for day, total in zip(days, totals[:, 0, 0], strict=True) if total
    }


@pytest.mark.req("R-4.1-7")
def test_the_local_day_total_three_hours_behind_utc() -> None:
    # Rain, hour by hour in UTC, and the local day (UTC-3) each hour belongs to:
    #   10 Jan 01-02 UTC: 2 mm   -> 9 Jan, 22-23 local
    #   10 Jan 10-11 UTC: 5 mm   -> 10 Jan
    #   11 Jan 01-02 UTC: 7 mm   -> 10 Jan, 22-23 local
    #   11 Jan 20-21 UTC: 1 mm   -> 11 Jan
    #   1 Jan 2002 01-02 UTC: 4 mm -> 31 Dec 2001, which needs the next year's first day
    # `tp` restarts after 00 UTC, and the value at 00:00 is the total of the day before.
    stamps, tp = two_steps(
        2001,
        3,
        {
            "2001-01-10T03": 2.0,  # 00-03 UTC of 10 Jan
            "2001-01-11T00": 7.0,  # the whole of 10 Jan UTC: 2 + 5
            "2001-01-11T03": 7.0,  # 00-03 UTC of 11 Jan
            "2001-01-12T00": 8.0,  # the whole of 11 Jan UTC: 7 + 1
            "2002-01-01T03": 4.0,  # 00-03 UTC of 1 Jan 2002
        },
    )

    days, totals = local_day_totals(stamps, tp, 2001, 3)

    assert (days[0], days[-1]) == (np.datetime64("2001-01-01"), np.datetime64("2001-12-31"))
    assert len(days) == 365
    assert totals.shape == (365, 1, 1)
    assert totals_by_day(days, totals) == {
        "2001-01-09": 2.0,
        "2001-01-10": 12.0,  # 5 + 7
        "2001-01-11": 1.0,
        "2001-12-31": 4.0,
    }
    assert totals.sum() == 2 + 5 + 7 + 1 + 4  # every millimetre lands in exactly one day


def test_the_local_day_total_four_hours_behind_utc() -> None:
    # 3 mm fall at 03-04 UTC of 10 Jan: 23-24 local on 9 Jan at UTC-4, but already 10 Jan
    # at UTC-3. 6 mm fall at 12-13 UTC of 10 Jan.
    values_at_4 = {"2001-01-10T04": 3.0, "2001-01-11T00": 9.0}
    values_at_3 = {"2001-01-10T03": 0.0, "2001-01-11T00": 9.0}

    behind_4 = totals_by_day(*local_day_totals(*two_steps(2001, 4, values_at_4), 2001, 4))
    behind_3 = totals_by_day(*local_day_totals(*two_steps(2001, 3, values_at_3), 2001, 3))

    assert behind_4 == {"2001-01-09": 3.0, "2001-01-10": 6.0}
    assert behind_3 == {"2001-01-10": 9.0}


def test_a_leap_year_has_366_local_days_and_the_order_of_the_steps_is_free() -> None:
    # 1.5 mm at 01-02 UTC of 1 March: 22-23 local on 29 February.
    stamps, tp = two_steps(2004, 3, {"2004-03-01T03": 1.5, "2004-03-02T00": 1.5})
    shuffled = np.random.default_rng(0).permutation(len(stamps))

    days, totals = local_day_totals(stamps[shuffled], tp[shuffled], 2004, 3)

    assert len(days) == 366
    assert totals_by_day(days, totals) == {"2004-02-29": 1.5}


def test_rounding_noise_becomes_zero_and_a_real_negative_fails() -> None:
    noise, tp = two_steps(2001, 3, {"2001-01-10T03": ROUNDING_NOISE_M / 2})
    days, totals = local_day_totals(noise, tp, 2001, 3)
    # 9 Jan gets the half micrometre, 10 Jan would get minus it: taken as zero.
    assert totals.min() == 0.0
    assert totals_by_day(days, totals) == {"2001-01-09": ROUNDING_NOISE_M / 2}

    stamps, wrong = two_steps(2001, 3, {"2001-01-10T03": 0.002})
    with pytest.raises(EarthEngineResponseError, match="negative"):
        local_day_totals(stamps, wrong, 2001, 3)


def test_missing_values_stay_missing() -> None:
    stamps, tp = two_steps(2001, 3, {"2001-01-10T03": float("nan")})

    _, totals = local_day_totals(stamps, tp, 2001, 3)

    assert np.isnan(totals[:, 0, 0]).sum() == 2  # the two local days that use the step


@pytest.mark.parametrize(
    ("drop", "add", "message"),
    [
        ("2001-06-01T03", None, "missing: 2001-06-01T03"),
        ("2002-01-01T00", None, "missing: 2002-01-01T00"),
        (None, "2001-06-01T05", "unexpected: 2001-06-01T05"),
        (None, "2001-06-01T03", "repeated: 2001-06-01T03"),
        # Midnight of 1 January closes the year before: it does not belong here.
        (None, "2001-01-01T00", "unexpected: 2001-01-01T00"),
    ],
)
def test_wrong_time_steps_fail(drop: str | None, add: str | None, message: str) -> None:
    stamps, tp = two_steps(2001, 3, {})
    if drop is not None:
        keep = stamps != np.datetime64(drop, "ms")
        stamps, tp = stamps[keep], tp[keep]
    if add is not None:
        stamps = np.append(stamps, np.datetime64(add, "ms"))
        tp = np.concatenate([tp, np.zeros((1, 1, 1))])

    with pytest.raises(EarthEngineResponseError, match=message):
        local_day_totals(stamps, tp, 2001, 3)


def test_the_time_steps_of_another_offset_fail() -> None:
    stamps, tp = two_steps(2001, 4, {})

    with pytest.raises(EarthEngineResponseError, match="wrong time steps for 2001"):
        local_day_totals(stamps, tp, 2001, 3)


# The request, as a table. The collection, band and grid fields follow the Earth Engine
# catalogue and the `computePixels` reference (ADR 0019), and served the real build at
# human gate H1.

REGIONS = {
    region_id: region
    for region_id in ("sul-de-minas", "sorriso", "ribeirao-preto")
    if (region := region_by_id(region_id)) is not None
}


@pytest.mark.req("R-4.1-7")
def test_the_request_for_a_region_and_year() -> None:
    request = year_request(SORRISO, 1987)

    assert request == YearRequest(
        collection="ECMWF/ERA5_LAND/HOURLY",
        band="total_precipitation",
        hours=(0, 4),  # Mato Grosso is four hours behind UTC
        start=datetime(1987, 1, 1, 1, tzinfo=UTC),
        end=datetime(1988, 1, 1, 5, tzinfo=UTC),  # exclusive: 04:00 of 1 January is the last
        grid={
            "crsCode": "EPSG:4326",
            "affineTransform": {
                "scaleX": 0.1,
                "shearX": 0,
                "translateX": -56.75,  # the region's western edge
                "shearY": 0,
                "scaleY": -0.1,
                "translateY": -11.55,  # its northern edge: row 0 is the northern row
            },
            "dimensions": {"width": 20, "height": 20},
        },
    )
    steps = request.expected_steps()
    assert len(steps) == 365 + 366  # 00:00 from 2 Jan to 1 Jan, 04:00 from 1 Jan to 1 Jan
    assert (steps[0], steps[1], steps[-1]) == (
        np.datetime64("1987-01-01T04"),
        np.datetime64("1987-01-02T00"),
        np.datetime64("1988-01-01T04"),
    )


def test_pixel_centres_are_the_cell_centres_of_every_region() -> None:
    for region in REGIONS.values():
        transform = year_request(region, 2000).grid["affineTransform"]
        for row, col in ((0, 0), (region.ny - 1, region.nx - 1)):
            lat = transform["translateY"] + (row + 0.5) * transform["scaleY"]
            lon = transform["translateX"] + (col + 0.5) * transform["scaleX"]
            assert np.allclose((lat, lon), cell_centre(region, row, col), atol=1e-9)


def test_the_time_steps_follow_the_offset_of_each_region() -> None:
    hours = {region_id: year_request(region, 2000).hours for region_id, region in REGIONS.items()}

    assert hours == {"sul-de-minas": (0, 3), "sorriso": (0, 4), "ribeirao-preto": (0, 3)}


def test_a_year_fits_in_one_request() -> None:
    # 733 bands of a leap year at most, against the 1024 of one `computePixels` request.
    assert max(len(year_request(SORRISO, year).expected_steps()) for year in (2003, 2004)) == 733


# The download step, with answers made the way Earth Engine is assumed to answer.

NATIVE_TRANSFORM = (0.1, 0.0, -180.05, 0.0, -0.1, 90.05)


@dataclass
class FakeEarthEngine:
    """Answers a request from an hourly rain rule, and records it.

    0.1 mm falls every hour at cell (0, 0); `showers` add rain in one hour (named by its
    end, in UTC) at one cell. `tp` at hour H of a day is the rain of that day from 00 UTC
    to H; the value stamped 00:00 is the whole previous UTC day.
    """

    showers: Mapping[str, tuple[int, int, float]] = field(default_factory=dict)
    change: Callable[[Answer], Answer] = lambda answer: answer
    requests: list[YearRequest] = field(default_factory=list)

    def fetch(self, request: YearRequest) -> Answer:
        self.requests.append(request)
        height = request.grid["dimensions"]["height"]
        width = request.grid["dimensions"]["width"]
        steps = request.expected_steps()
        ids = [str(step).replace("-", "") for step in steps]  # 19870101T04
        names = [f"{image_id}_{request.band}" for image_id in ids]
        pixels = np.zeros((height, width), dtype=[(name, np.float32) for name in names])
        for step, name in zip(steps, names, strict=True):
            start = (step - HOUR).astype("datetime64[D]").astype("datetime64[h]") + HOUR
            values = np.zeros((height, width))
            values[0, 0] = int((step - start) / HOUR + 1) * 0.0001
            for end, (row, col, millimetres) in self.showers.items():
                if start <= np.datetime64(end, "h") <= step:
                    values[row, col] += millimetres / 1000
            pixels[name] = values
        times = (steps.astype("datetime64[ms]").astype(np.int64)).tolist()
        return self.change(
            Answer(
                native_crs="EPSG:4326",
                native_transform=NATIVE_TRANSFORM,
                image_ids=ids,
                time_starts_ms=times,
                pixels=pixels,
            )
        )


@pytest.mark.req("R-4.1-7")
def test_a_download_makes_one_request_and_writes_local_day_sums(tmp_path: Path) -> None:
    showers = {
        "1987-01-10T03": (1, 2, 3.0),  # 22-23 local on 9 Jan at UTC-4
        "1987-01-10T05": (1, 2, 2.0),  # 00-01 local on 10 Jan
        "1988-01-01T02": (2, 3, 4.0),  # 21-22 local on 31 Dec 1987: in the next year's answer
    }
    earth_engine = FakeEarthEngine(showers=showers)
    target = tmp_path / "1987.nc"

    EarthEngineYearlySource(earth_engine.fetch).download(SORRISO, 1987, target)

    assert earth_engine.requests == [year_request(SORRISO, 1987)]
    dates, millimetres = convert_to_arrays([target], SORRISO)
    assert (dates[0], dates[-1]) == (np.datetime64("1987-01-01"), np.datetime64("1987-12-31"))
    assert millimetres.shape == (365, 20, 20)
    # 0.1 mm an hour: every local day holds 2.4 mm, whatever the offset; metres became mm.
    assert np.allclose(millimetres[:, 0, 0], 2.4, rtol=1e-5)
    day = {str(date): index for index, date in enumerate(dates)}
    assert np.isclose(millimetres[day["1987-01-09"], 1, 2], 3.0, rtol=1e-5)
    assert np.isclose(millimetres[day["1987-01-10"], 1, 2], 2.0, rtol=1e-5)
    assert np.isclose(millimetres[day["1987-12-31"], 2, 3], 4.0, rtol=1e-5)
    assert np.isclose(millimetres[:, 1:, :].sum(), 9.0, rtol=1e-5)  # nothing else, nowhere
    assert sorted(path.name for path in tmp_path.iterdir()) == ["1987.nc"]
    with xr.open_dataset(target, engine="h5netcdf") as dataset:
        assert dataset.attrs["collection"] == "ECMWF/ERA5_LAND/HOURLY"
        assert dataset.attrs["band"] == "total_precipitation"
        assert "UTC-4" in dataset.attrs["local_day"]


def _rename_first_band(answer: Answer) -> Answer:
    pixels = answer.pixels.copy()
    names = list(pixels.dtype.names or ())
    names[0], names[1] = names[1], names[0]
    pixels.dtype.names = tuple(names)
    return replace(answer, pixels=pixels)


def _drop_last_step(answer: Answer) -> Answer:
    names = list(answer.pixels.dtype.names or ())[:-1]
    return replace(
        answer,
        image_ids=answer.image_ids[:-1],
        time_starts_ms=answer.time_starts_ms[:-1],
        pixels=answer.pixels[names],
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda a: replace(a, native_crs="EPSG:3857"), "native projection is EPSG:3857"),
        (
            lambda a: replace(a, native_transform=(0.1, 0.0, -180.0, 0.0, -0.1, 90.0)),
            "would resample",
        ),
        (
            lambda a: replace(a, native_transform=(0.25, 0.0, -180.125, 0.0, -0.25, 90.125)),
            "would resample",
        ),
        (lambda a: replace(a, pixels=a.pixels[:, :19]), r"shape \(20, 19\)"),
        (_rename_first_band, "are not the images"),
        (lambda a: replace(a, image_ids=a.image_ids[:-1]), "image ids for"),
        (_drop_last_step, "are not the 731 expected"),
        (
            lambda a: replace(a, time_starts_ms=[t + 1_800_000 for t in a.time_starts_ms]),
            "are not the 731 expected",
        ),
    ],
)
def test_an_answer_that_is_not_the_expected_one_fails_and_writes_no_file(
    tmp_path: Path, change: Callable[[Answer], Answer], message: str
) -> None:
    earth_engine = FakeEarthEngine(change=change)
    target = tmp_path / "1987.nc"

    with pytest.raises(EarthEngineResponseError, match=message):
        EarthEngineYearlySource(earth_engine.fetch).download(SORRISO, 1987, target)

    assert list(tmp_path.iterdir()) == []


def test_a_response_error_is_a_weather_data_error() -> None:
    assert issubclass(EarthEngineResponseError, WeatherDataError)  # reported as failed


# The client set-up, over a fake `ee`: refusals come before any download.


@pytest.fixture
def fake_ee(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Fake `ee`, `httplib2` and `google.auth.exceptions` modules, recording calls."""

    class EEException(Exception):  # noqa: N818 - the name of the client's class
        pass

    class HttpLib2Error(Exception):
        pass

    class RefreshError(Exception):
        pass

    class TransportError(Exception):
        pass

    state = types.SimpleNamespace(
        credentials=True, initialize_error=None, initialized=[], EEException=EEException
    )

    def get_persistent_credentials() -> object:
        if not state.credentials:
            raise EEException("Please authorize access ... earthengine authenticate ...")
        return object()

    def initialize(project: str) -> None:
        if state.initialize_error is not None:
            raise state.initialize_error
        state.initialized.append(project)

    namespace = types.SimpleNamespace
    auth_exceptions = namespace(RefreshError=RefreshError, TransportError=TransportError)
    modules = {
        "ee": namespace(
            EEException=EEException,
            Initialize=initialize,
            data=namespace(get_persistent_credentials=get_persistent_credentials),
        ),
        "httplib2": namespace(HttpLib2Error=HttpLib2Error),
        "google.auth": namespace(exceptions=auth_exceptions),
        "google.auth.exceptions": auth_exceptions,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    state.RefreshError = RefreshError
    return state


@pytest.mark.req("R-4.1-6")
def test_without_stored_credentials_the_setup_names_the_command(
    fake_ee: types.SimpleNamespace,
) -> None:
    fake_ee.credentials = False

    with pytest.raises(EarthEngineSetupError, match="earthengine authenticate"):
        earth_engine_fetch("my-project")

    assert fake_ee.initialized == []


def test_the_setup_initialises_the_named_project(fake_ee: types.SimpleNamespace) -> None:
    earth_engine_fetch("my-project")

    assert fake_ee.initialized == ["my-project"]


def test_refused_credentials_name_the_command_again(fake_ee: types.SimpleNamespace) -> None:
    fake_ee.initialize_error = fake_ee.RefreshError("invalid_grant")

    with pytest.raises(EarthEngineSetupError, match="earthengine authenticate --force"):
        earth_engine_fetch("my-project")


def test_a_project_earth_engine_refuses_is_one_line(fake_ee: types.SimpleNamespace) -> None:
    fake_ee.initialize_error = fake_ee.EEException(
        "Project my-project is not registered.\nSee the registration page."
    )

    with pytest.raises(EarthEngineRefusedError) as raised:
        earth_engine_fetch("my-project")

    assert str(raised.value) == (
        "Earth Engine refused the request: Project my-project is not registered."
    )


def test_no_network_during_the_setup_is_unreachable(fake_ee: types.SimpleNamespace) -> None:
    fake_ee.initialize_error = OSError("name resolution failed")

    with pytest.raises(EarthEngineUnreachableError):
        earth_engine_fetch("my-project")


# The yearly cache.


@dataclass
class InMemoryYearlySource:
    """Writes synthetic yearly files and counts the years asked."""

    fail_on: int | None = None
    downloads: list[int] = field(default_factory=list)

    def download(self, region: RegionDef, year: int, target: Path) -> None:
        self.downloads.append(year)
        if year == self.fail_on:
            target.write_bytes(b"half a file")
            raise ConnectionError("the download broke")
        write_synthetic_year(target, region, year, seed=9)

    def provenance(self, region: RegionDef) -> dict[str, str]:
        return {"dataset": "in-memory", "region": region.region_id}


def builder(root: Path, source: InMemoryYearlySource) -> tuple[BuildCube, LocalWeatherStore]:
    store = LocalWeatherStore(root / "weather", CLOCK)
    return BuildCube(store, source, convert_to_arrays, file_checksum, root / "cache"), store


@pytest.mark.req("R-4.1-4")
async def test_a_rerun_downloads_nothing_and_a_removed_year_only_that_year(tmp_path: Path) -> None:
    source = InMemoryYearlySource()
    build, _ = builder(tmp_path, source)

    first = await build(SORRISO, 2001, 2003)
    again = await build(SORRISO, 2001, 2003)
    (tmp_path / "cache" / "sorriso" / "2002.nc").unlink()
    third = await build(SORRISO, 2001, 2003)

    assert source.downloads == [2001, 2002, 2003, 2002]
    assert (first.downloaded, first.reused) == ((2001, 2002, 2003), ())
    assert (again.downloaded, again.reused) == ((), (2001, 2002, 2003))
    assert (third.downloaded, third.reused) == ((2002,), (2001, 2003))


@pytest.mark.req("R-4.1-4")
async def test_a_file_without_its_sidecar_or_changed_since_is_downloaded_again(
    tmp_path: Path,
) -> None:
    source = InMemoryYearlySource()
    build, _ = builder(tmp_path, source)
    cache = tmp_path / "cache" / "sorriso"
    await build(SORRISO, 2001, 2003)
    assert sorted(path.name for path in cache.iterdir()) == [
        "2001.nc",
        "2001.nc.sha256",
        "2002.nc",
        "2002.nc.sha256",
        "2003.nc",
        "2003.nc.sha256",
    ]
    assert (cache / "2001.nc.sha256").read_text().strip() == file_checksum(cache / "2001.nc")

    (cache / "2001.nc.sha256").unlink()
    (cache / "2003.nc").write_bytes(b"changed after the download")
    await build(SORRISO, 2001, 2003)

    assert source.downloads == [2001, 2002, 2003, 2001, 2003]


@pytest.mark.req("R-4.1-4")
async def test_a_broken_download_leaves_no_file_and_installs_no_cube(tmp_path: Path) -> None:
    source = InMemoryYearlySource(fail_on=2002)
    build, store = builder(tmp_path, source)

    with pytest.raises(ConnectionError):
        await build(SORRISO, 2001, 2003)

    cache = tmp_path / "cache" / "sorriso"
    assert sorted(path.name for path in cache.iterdir()) == ["2001.nc", "2001.nc.sha256"]
    assert await store.cube_source("sorriso") is None

    source.fail_on = None
    await build(SORRISO, 2001, 2003)
    assert source.downloads == [2001, 2002, 2002, 2003]  # 2001 was kept


@pytest.mark.req("R-4.1-1", "R-4.1-5")
async def test_a_real_build_installs_a_cube_that_is_not_synthetic(tmp_path: Path) -> None:
    build, store = builder(tmp_path, InMemoryYearlySource())

    report = await build(SORRISO, 2001, 2002)

    cube = await store.read_cube("sorriso")
    cache = tmp_path / "cache" / "sorriso"
    manifest = json.loads((tmp_path / "weather/climate/cubes/sorriso/manifest.json").read_text())
    assert report.source == "era5-land/cds"  # the frozen label of ERA5-Land (ADR 0019)
    assert cube.region.synthetic is False
    assert cube.precipitation_mm.shape == (730, 20, 20)
    assert (await store.describe(cube_dataset_id("sorriso", 3, 4))).source == "era5-land/cds"
    assert manifest["request"] == {"dataset": "in-memory", "region": "sorriso"}
    assert manifest["year_checksums"] == {
        "2001": file_checksum(cache / "2001.nc"),
        "2002": file_checksum(cache / "2002.nc"),
    }


@pytest.mark.req("R-4.1-1")
async def test_a_synthetic_build_installs_a_cube_labelled_synthetic(tmp_path: Path) -> None:
    store = LocalWeatherStore(tmp_path / "weather", CLOCK)
    install = InstallSyntheticCube(store, generate_cube, GENERATOR, generator_parameters())

    report = await install(SUL_DE_MINAS, 2001, 2002, 7)

    cube = await store.read_cube("sul-de-minas")
    expected = generate_cube(SUL_DE_MINAS, 2001, 2002, 7)
    manifest = json.loads(
        (tmp_path / "weather/climate/cubes/sul-de-minas/manifest.json").read_text()
    )
    assert (report.source, report.downloaded, report.reused) == ("synthetic", (), ())
    assert cube.region.synthetic is True
    assert np.array_equal(cube.precipitation_mm, expected.precipitation_mm)
    assert (await store.describe(cube_dataset_id("sul-de-minas", 0, 0))).source == "synthetic"
    assert manifest["source"] == "synthetic"
    assert manifest["year_checksums"] == {}  # no yearly file was read
    assert manifest["request"] == {
        "generator": "veranico-synthetic/1",
        "seed": "7",
        "first_year": "2001",
        "last_year": "2002",
        **generator_parameters(),
    }
    assert manifest["request"]["gamma_shape"] == "0.75"


# The script.


@pytest.fixture
def script_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The store under `tmp_path`, two years of history, and no Earth Engine project."""
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_BACKEND", "local")
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_ROOT", str(tmp_path / "weather"))
    monkeypatch.setenv("VERANICO_CLIMATE__FIRST_YEAR", "2024")
    monkeypatch.delenv("EARTHENGINE_PROJECT", raising=False)
    monkeypatch.setattr(script, "YEARLY_CACHE", tmp_path / "yearly-cache")
    return tmp_path / "weather"


@pytest.mark.req("R-4.1-6")
def test_without_a_project_the_script_reports_the_gate_open(
    script_environment: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_client(project: str) -> download.Fetch:
        raise AssertionError("the client must not be set up without a project")

    monkeypatch.setattr(script, "earth_engine_fetch", no_client)

    assert script.main(["--region", "sorriso"]) == 3

    captured = capsys.readouterr()
    assert "EARTHENGINE_PROJECT is not set" in captured.err
    assert "EARTHENGINE_PROJECT=<project-id>" in captured.err
    assert "H1" in captured.err
    assert captured.out == ""
    assert not script_environment.exists()  # nothing was installed


def test_an_empty_project_is_no_project(
    script_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARTHENGINE_PROJECT", "  ")

    assert script.main(["--region", "sorriso"]) == 3


def test_without_credentials_the_script_names_the_command_before_any_download(
    script_environment: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_credentials(project: str) -> download.Fetch:
        raise EarthEngineSetupError(
            f"no Earth Engine credentials are stored: run `{download.AUTHENTICATE_COMMAND}` once"
        )

    monkeypatch.setenv("EARTHENGINE_PROJECT", "my-project")
    monkeypatch.setattr(script, "earth_engine_fetch", no_credentials)

    assert script.main(["--region", "sorriso"]) == 3

    captured = capsys.readouterr()
    assert captured.err == (
        "build_cube: open, no Earth Engine credentials are stored: run "
        "`cd backend && uv run --group cube earthengine authenticate` once\n"
    )
    assert not script_environment.exists()
    assert not (script_environment.parent / "yearly-cache").exists()  # nothing downloaded


def test_the_script_installs_a_synthetic_cube(
    script_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "ribeirao-preto", "--synthetic", "--seed", "5"]) == 0

    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads(
        (script_environment / "climate/cubes/ribeirao-preto/manifest.json").read_text()
    )
    assert summary["region_id"] == "ribeirao-preto"
    assert (summary["source"], summary["seed"], summary["first_year"]) == ("synthetic", 5, 2024)
    assert manifest["source"] == "synthetic"
    assert manifest["request"]["seed"] == "5"
    assert manifest["years"][0] == 2024
    assert manifest["years"][-1] == summary["last_year"]


def test_the_default_seed_is_1(
    script_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "sorriso", "--synthetic"]) == 0

    assert json.loads(capsys.readouterr().out)["seed"] == 1


def test_an_unknown_region_fails(
    script_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "atlantis", "--synthetic"]) == 1

    assert "unknown region 'atlantis'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "code", "line"),
    [
        (
            EarthEngineRefusedError("Earth Engine refused the request: Project is not registered"),
            1,
            "build_cube: failed, Earth Engine refused the request: Project is not registered\n",
        ),
        (
            EarthEngineUnreachableError("no answer"),
            3,
            "build_cube: open, no answer from Earth Engine\n",
        ),
        (
            EarthEngineResponseError("the native projection is EPSG:3857"),
            1,
            "build_cube: failed, the native projection is EPSG:3857\n",
        ),
    ],
)
def test_a_refused_or_unreachable_download_is_one_line_and_no_traceback(
    script_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    code: int,
    line: str,
) -> None:
    def fetch(request: YearRequest) -> Answer:
        raise error

    monkeypatch.setenv("EARTHENGINE_PROJECT", "my-project")
    monkeypatch.setattr(script, "earth_engine_fetch", lambda project: fetch)

    assert script.main(["--region", "sorriso"]) == code

    captured = capsys.readouterr()
    assert captured.err == line
    assert not script_environment.exists()  # no cube was installed


# The service never loads the Earth Engine client.

_PROBE = """
import sys
from tests.fakes.settings import settings_for_tests
from veranico.main import create_app
import veranico.modules.climate.infrastructure.earth_engine_download

create_app(settings_for_tests("api", firestore_emulator_host="127.0.0.1:8580"))
print(sorted(name for name in sys.modules if name.split(".")[0] in ("ee", "httplib2")))
"""


@pytest.mark.req("R-4.1-6")
def test_creating_the_api_application_leaves_the_earth_engine_client_unloaded() -> None:
    # A new interpreter, so what other tests imported does not matter. The download module
    # itself is imported too: even that must not load the client.
    backend = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"


def test_a_raw_answer_with_a_year_of_bands_loads_without_pickles() -> None:
    """A structured array of 733 named bands has a header over NumPy's default limit."""
    import io

    fields = [(f"2024010{n:04d}_total_precipitation", "<f4") for n in range(733)]
    array = np.zeros((20, 20), dtype=fields)
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)

    loaded = download.load_npy(buffer.getvalue())

    assert loaded.dtype.names == array.dtype.names
    assert loaded.shape == (20, 20)


def test_a_raw_answer_holding_pickled_objects_is_refused() -> None:
    import io

    buffer = io.BytesIO()
    np.save(buffer, np.array([{"not": "pixels"}], dtype=object), allow_pickle=True)

    with pytest.raises(ValueError, match="allow_pickle"):
        download.load_npy(buffer.getvalue())
