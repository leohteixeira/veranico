"""The cube build: the CDS download step, the yearly cache, the script and its exit codes."""

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr
from scripts import build_cube as script

from veranico.modules.climate.application.build_cube import BuildCube, InstallSyntheticCube
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.regions import RegionDef, region_by_id
from veranico.modules.climate.infrastructure.cds_download import (
    ROUNDING_NOISE_M,
    CdsResponseError,
    CdsYearlySource,
    local_day_totals,
    next_day_request,
    year_request,
)
from veranico.modules.climate.infrastructure.cube_build import convert_to_arrays, file_checksum
from veranico.modules.climate.infrastructure.local_store import LocalWeatherStore
from veranico.modules.climate.infrastructure.synthetic import (
    GENERATOR,
    generate_cube,
    generator_parameters,
    write_synthetic_cds_year,
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


# The two-step formula of ADR 0018, on a series written by hand.


def two_steps(year: int, offset: int, values: Mapping[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """Accumulated `tp` of one cell at 00:00 and `offset`:00 of every day of `year` and of
    1 January of the next: zero, except the time steps named in `values`."""
    days = np.arange(f"{year}-01-01", f"{year + 1}-01-02", dtype="datetime64[D]")
    midnight = days.astype("datetime64[h]")
    stamps = np.concatenate([midnight, midnight + np.timedelta64(offset, "h")])
    tp = np.zeros((len(stamps), 1, 1))
    for stamp, value in values.items():
        (index,) = np.nonzero(stamps == np.datetime64(stamp, "h"))
        tp[index[0], 0, 0] = value
    return stamps.astype("datetime64[ns]"), tp


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
    with pytest.raises(CdsResponseError, match="negative"):
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
    ],
)
def test_wrong_time_steps_fail(drop: str | None, add: str | None, message: str) -> None:
    stamps, tp = two_steps(2001, 3, {})
    if drop is not None:
        keep = stamps != np.datetime64(drop, "ns")
        stamps, tp = stamps[keep], tp[keep]
    if add is not None:
        stamps = np.append(stamps, np.datetime64(add, "ns"))
        tp = np.concatenate([tp, np.zeros((1, 1, 1))])

    with pytest.raises(CdsResponseError, match=message):
        local_day_totals(stamps, tp, 2001, 3)


def test_the_time_steps_of_another_offset_fail() -> None:
    stamps, tp = two_steps(2001, 4, {})

    with pytest.raises(CdsResponseError, match="wrong time steps for 2001"):
        local_day_totals(stamps, tp, 2001, 3)


# The request, as a table. NOT verified against the CDS (human gate H1): the keys follow
# the request form of the catalogue entry as far as it could be read without an account.


@pytest.mark.req("R-4.1-7")
def test_the_request_for_a_region_and_year() -> None:
    assert year_request(SORRISO, 1987) == {
        "variable": ["total_precipitation"],
        "year": ["1987"],
        "month": ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"],
        "day": [f"{day:02d}" for day in range(1, 32)],
        "time": ["00:00", "04:00"],  # Mato Grosso is four hours behind UTC
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [-11.6, -56.7, -13.5, -54.8],  # N, W, S, E: the outermost grid points
    }
    assert next_day_request(SORRISO, 1987) == {
        "variable": ["total_precipitation"],
        "year": ["1988"],
        "month": ["01"],
        "day": ["01"],
        "time": ["00:00", "04:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [-11.6, -56.7, -13.5, -54.8],
    }


def test_the_time_steps_follow_the_offset_of_each_region() -> None:
    steps = {region_id: year_request(region, 2000)["time"] for region_id, region in REGIONS.items()}

    assert steps == {
        "sul-de-minas": ["00:00", "03:00"],
        "sorriso": ["00:00", "04:00"],
        "ribeirao-preto": ["00:00", "03:00"],
    }


REGIONS = {
    region_id: region
    for region_id in ("sul-de-minas", "sorriso", "ribeirao-preto")
    if (region := region_by_id(region_id)) is not None
}


# The download step, with answers written the way the CDS is assumed to answer.


@dataclass
class FakeCds:
    """Answers every request with a file made from an hourly rain rule, and records it."""

    rename: dict[str, str] = field(default_factory=dict)
    units: str = "m"
    drop_last_longitude: bool = False
    requests: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)

    def retrieve(self, dataset: str, request: Mapping[str, Any], target: Path) -> None:
        self.requests.append((dataset, request))
        north, west, south, east = request["area"]
        latitudes = np.linspace(north, south, 20).astype(np.float32)
        longitudes = np.linspace(west, east, 20).astype(np.float32)
        if self.drop_last_longitude:
            longitudes = longitudes[:-1]
        stamps = np.array(
            [
                np.datetime64(f"{year}-{month}-{day}T{time[:2]}", "h")
                for year in request["year"]
                for month in request["month"]
                for day in request["day"]
                for time in request["time"]
                if _exists(year, month, day)
            ]
        )
        # Every hour of the record rains 0.1 mm at cell (0, 0), nothing elsewhere: the
        # accumulation at hour H is H tenths of a millimetre, and a whole day (00:00) 2.4 mm.
        hour = (stamps - stamps.astype("datetime64[D]")).astype(np.int64)
        tp = np.zeros((len(stamps), len(latitudes), len(longitudes)), dtype=np.float32)
        tp[:, 0, 0] = np.where(hour == 0, 24, hour) * 0.0001
        dataset_out = xr.Dataset(
            {"tp": (("valid_time", "latitude", "longitude"), tp, {"units": self.units})},
            coords={
                "valid_time": stamps.astype("datetime64[ns]"),
                "latitude": latitudes,
                "longitude": longitudes,
                "number": 0,
                "expver": "0001",
            },
        ).rename(self.rename)
        dataset_out.to_netcdf(target, engine="h5netcdf")


def _exists(year: str, month: str, day: str) -> bool:
    try:
        datetime(int(year), int(month), int(day), tzinfo=UTC)
    except ValueError:
        return False
    return True


@pytest.mark.req("R-4.1-7")
def test_a_download_makes_two_requests_and_writes_local_day_sums(tmp_path: Path) -> None:
    cds = FakeCds()
    target = tmp_path / "1987.nc"

    CdsYearlySource(cds.retrieve).download(SORRISO, 1987, target)

    assert cds.requests == [
        ("reanalysis-era5-land", year_request(SORRISO, 1987)),
        ("reanalysis-era5-land", next_day_request(SORRISO, 1987)),
    ]
    dates, millimetres = convert_to_arrays([target], SORRISO)
    assert (dates[0], dates[-1]) == (np.datetime64("1987-01-01"), np.datetime64("1987-12-31"))
    assert millimetres.shape == (365, 20, 20)
    # 0.1 mm an hour: every local day holds 2.4 mm, whatever the offset.
    assert np.allclose(millimetres[:, 0, 0], 2.4, rtol=1e-5)
    assert millimetres[:, 1:, :].sum() == 0.0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["1987.nc"]  # no scratch left
    with xr.open_dataset(target, engine="h5netcdf") as dataset:
        assert dataset.attrs["source"] == "era5-land/cds"
        assert dataset.attrs["dataset"] == "reanalysis-era5-land"
        assert "UTC-4" in dataset.attrs["local_day"]


@pytest.mark.parametrize(
    ("cds", "message"),
    [
        (FakeCds(rename={"tp": "total_precipitation"}), "no variable 'tp' in the answer"),
        (FakeCds(rename={"valid_time": "time"}), "has dimensions"),
        (FakeCds(rename={"latitude": "lat"}), "has dimensions"),
        (FakeCds(units="mm"), "is in 'mm', expected 'm'"),
        (FakeCds(drop_last_longitude=True), "does not cover the region"),
    ],
)
def test_an_answer_that_is_not_the_expected_one_fails_and_writes_no_file(
    tmp_path: Path, cds: FakeCds, message: str
) -> None:
    target = tmp_path / "1987.nc"

    with pytest.raises(CdsResponseError, match=message):
        CdsYearlySource(cds.retrieve).download(SORRISO, 1987, target)

    assert list(tmp_path.iterdir()) == []


def test_an_answer_that_is_not_netcdf_fails(tmp_path: Path) -> None:
    def retrieve(dataset: str, request: Mapping[str, Any], target: Path) -> None:
        target.write_bytes(b"PK\x03\x04 a zip archive, not NetCDF")

    with pytest.raises(CdsResponseError, match="not a NetCDF file"):
        CdsYearlySource(retrieve).download(SORRISO, 1987, tmp_path / "1987.nc")

    assert list(tmp_path.iterdir()) == []


def test_a_cds_error_is_a_weather_data_error() -> None:
    assert issubclass(CdsResponseError, WeatherDataError)  # the script reports it as failed


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
        write_synthetic_cds_year(target, region, year, seed=9)

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
    assert report.source == "era5-land/cds"
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
    """The store under `tmp_path`, two years of history, and no CDS key."""
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_BACKEND", "local")
    monkeypatch.setenv("VERANICO_CLIMATE__STORE_ROOT", str(tmp_path / "weather"))
    monkeypatch.setenv("VERANICO_CLIMATE__FIRST_YEAR", "2024")
    monkeypatch.delenv("CDS_API_KEY", raising=False)
    return tmp_path / "weather"


def test_without_a_cds_key_the_script_reports_the_gate_open(
    script_environment: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--region", "sorriso"]) == 3

    captured = capsys.readouterr()
    assert "CDS_API_KEY is not set" in captured.err
    assert "H1" in captured.err
    assert captured.out == ""
    assert not script_environment.exists()  # nothing was installed


def test_an_empty_cds_key_is_no_key(
    script_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CDS_API_KEY", "  ")

    assert script.main(["--region", "sorriso"]) == 3


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
            script.CdsRefusedError("the Climate Data Store refused the request: 401 Unauthorized"),
            1,
            "build_cube: failed, the Climate Data Store refused the request: 401 Unauthorized\n",
        ),
        (
            script.CdsUnreachableError("no answer"),
            3,
            "build_cube: open, no answer from the Climate Data Store\n",
        ),
    ],
)
def test_a_refused_or_unreachable_cds_is_one_line_and_no_traceback(
    script_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    code: int,
    line: str,
) -> None:
    def retrieve(dataset: str, request: Mapping[str, Any], target: Path) -> None:
        raise error

    monkeypatch.setenv("CDS_API_KEY", "not-a-real-token")
    monkeypatch.setattr(script, "cdsapi_retrieve", lambda key: retrieve)
    monkeypatch.setattr(script, "CDS_CACHE", script_environment.parent / "cds-cache")

    assert script.main(["--region", "sorriso"]) == code

    captured = capsys.readouterr()
    assert captured.err == line
    assert "not-a-real-token" not in captured.err + captured.out
    assert not script_environment.exists()  # no cube was installed


# The service never loads the CDS client.

_PROBE = """
import sys
from tests.fakes.settings import settings_for_tests
from veranico.main import create_app
import veranico.modules.climate.infrastructure.cds_download

create_app(settings_for_tests("api", firestore_emulator_host="127.0.0.1:8580"))
print(sorted(name for name in sys.modules if name.split(".")[0] == "cdsapi"))
"""


@pytest.mark.req("R-4.1-6")
def test_creating_the_api_application_leaves_the_cds_client_unloaded() -> None:
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
