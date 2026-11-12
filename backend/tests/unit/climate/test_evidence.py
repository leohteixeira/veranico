"""Evidence export: the exact window days of the priced seasons, as NetCDF with provenance."""

import io
import json

import numpy as np
import pytest
import xarray as xr

from tests.unit.climate.fakes import FAKE_CHECKSUM, InMemoryWeatherStore, rain_for, year_days
from veranico.modules.climate.application.cells import h3_cell_of
from veranico.modules.climate.application.export_evidence import ExportEvidence
from veranico.modules.climate.contracts import DailySeries, DatasetRef, EvidenceRequest, GridPoint
from veranico.modules.climate.domain.window_days import window_mask
from veranico.modules.climate.infrastructure.netcdf import encode_evidence
from veranico.shared.kernel.errors import DatasetNotFoundError, InvalidArgumentsError
from veranico.shared.kernel.ids import point_dataset_id

GRID_POINT = GridPoint(lat=-15.0, lon=-48.0)
DATASET_ID = point_dataset_id(h3_cell_of(GRID_POINT.lat, GRID_POINT.lon))
REQUEST = {"url": "memory://archive", "models": "era5"}
INDEX = {"index_type": "rainfall_below", "trigger": "400.0", "exit": "200.0"}


def days(first: str, last: str) -> np.ndarray:
    return np.arange(first, np.datetime64(last) + np.timedelta64(1, "D"), dtype="datetime64[D]")


def store_with_series(first_year: int = 1998, last_year: int = 2004) -> InMemoryWeatherStore:
    dates = year_days(first_year, last_year)
    rain = rain_for(dates)
    rain[dates == np.datetime64("2001-01-10")] = np.nan  # a missing day inside a window
    store = InMemoryWeatherStore()
    store.series[DATASET_ID] = DailySeries(
        dataset=DatasetRef(
            dataset_id=DATASET_ID,
            kind="point",
            region_id=None,
            grid_point=GRID_POINT,
            first_year=first_year,
            last_year=last_year,
            days=len(dates),
            missing_days=1,
            source="era5/open-meteo",
        ),
        dates=dates,
        precipitation_mm=rain,
    )
    store.requests[DATASET_ID] = REQUEST
    return store


def request(
    start: str, end: str, first: int, last: int, attributes: dict[str, str] | None = None
) -> EvidenceRequest:
    return EvidenceRequest(
        dataset_id=DATASET_ID,
        window_start=start,
        window_end=end,
        first_season=first,
        last_season=last,
        attributes=INDEX if attributes is None else attributes,
    )


async def export(
    store: InMemoryWeatherStore, evidence_request: EvidenceRequest
) -> tuple[np.ndarray, np.ndarray, dict[str, str]]:
    data = await ExportEvidence(store, encode_evidence)(evidence_request)
    with xr.open_dataset(io.BytesIO(data), engine="h5netcdf") as dataset:
        assert list(dataset.data_vars) == ["precipitation_mm"]
        assert dataset["precipitation_mm"].attrs["units"] == "mm"
        return (
            dataset["time"].to_numpy().astype("datetime64[D]"),
            dataset["precipitation_mm"].to_numpy(),
            {str(key): str(value) for key, value in dataset.attrs.items()},
        )


# The day mask, without any file.


def test_a_window_inside_one_year_selects_its_days_in_each_season() -> None:
    dates = year_days(1999, 2002)

    mask = window_mask(dates, "09-01", "10-31", 2000, 2001)

    expected = np.concatenate([days("2000-09-01", "2000-10-31"), days("2001-09-01", "2001-10-31")])
    assert np.array_equal(dates[mask], expected)
    assert mask.sum() == 2 * 61


def test_a_window_crossing_the_year_runs_into_the_year_after_the_last_season() -> None:
    dates = year_days(1999, 2004)

    mask = window_mask(dates, "11-15", "02-15", 2000, 2002)

    selected = dates[mask]
    assert selected[0] == np.datetime64("2000-11-15")
    assert selected[-1] == np.datetime64("2003-02-15")  # season 2002 ends in early 2003
    assert np.datetime64("2000-02-15") not in selected  # that day belongs to season 1999
    assert np.datetime64("2003-11-15") not in selected  # season 2003 was not asked
    assert np.datetime64("2001-02-16") not in selected
    assert mask.sum() == 93 * 3  # 16 + 31 + 31 + 15 days, no leap day inside


def test_a_one_day_window_and_a_single_season() -> None:
    dates = year_days(2000, 2001)

    mask = window_mask(dates, "03-10", "03-10", 2001, 2001)

    assert list(dates[mask]) == [np.datetime64("2001-03-10")]


@pytest.mark.parametrize(
    ("start", "end"), [("02-29", "03-31"), ("13-01", "12-31"), ("1-1", "02-01"), ("01-01", "x")]
)
def test_a_malformed_bound_is_invalid(start: str, end: str) -> None:
    with pytest.raises(InvalidArgumentsError):
        window_mask(year_days(2000, 2001), start, end, 2000, 2000)


def test_a_reversed_season_range_is_invalid_for_the_mask() -> None:
    with pytest.raises(InvalidArgumentsError):
        window_mask(year_days(2000, 2001), "01-01", "01-31", 2001, 2000)


# The export, read back from the NetCDF bytes.


@pytest.mark.req("R-4.4-5")
async def test_a_same_year_window_reads_back_exactly_the_masked_days_and_values() -> None:
    store = store_with_series()

    dates, values, _ = await export(store, request("09-01", "10-31", 2000, 2002))

    expected = np.concatenate(
        [days(f"{year}-09-01", f"{year}-10-31") for year in (2000, 2001, 2002)]
    )
    assert np.array_equal(dates, expected)
    assert np.array_equal(values, rain_for(expected))
    assert values.dtype == np.float64


@pytest.mark.req("R-4.4-5")
async def test_a_crossing_window_holds_the_early_days_of_the_year_after_the_last_season() -> None:
    store = store_with_series()

    dates, values, _ = await export(store, request("11-15", "02-15", 2000, 2002))

    assert dates[0] == np.datetime64("2000-11-15")  # nothing before the 2000 window opens
    assert dates[-1] == np.datetime64("2003-02-15")  # nothing after the 2002 window closes
    assert np.datetime64("2003-01-20") in dates  # early 2003 belongs to season 2002
    assert len(dates) == 93 * 3
    full = store.series[DATASET_ID]
    mask = np.isin(full.dates, dates)
    assert np.array_equal(values, full.precipitation_mm[mask], equal_nan=True)
    assert np.isnan(values[dates == np.datetime64("2001-01-10")]).all()  # missing stays missing


@pytest.mark.req("R-4.4-5")
async def test_every_provenance_attribute_is_present_then_the_callers() -> None:
    store = store_with_series()

    _, _, attributes = await export(store, request("09-01", "10-31", 2000, 2002))

    assert attributes == {
        "dataset_id": DATASET_ID,
        "grid_point_lat": "-15.0",
        "grid_point_lon": "-48.0",
        "source": "era5/open-meteo",
        "request": json.dumps(REQUEST, sort_keys=True),
        "manifest_checksum": FAKE_CHECKSUM,
        "window_start": "09-01",
        "window_end": "10-31",
        "first_season": "2000",
        "last_season": "2002",
        **INDEX,
    }


async def test_the_same_request_gives_the_same_bytes() -> None:
    store = store_with_series()
    evidence_request = request("09-01", "10-31", 2000, 2002)

    first = await ExportEvidence(store, encode_evidence)(evidence_request)
    second = await ExportEvidence(store, encode_evidence)(evidence_request)

    assert first == second
    assert first[:4] == b"\x89HDF"  # NetCDF-4 is an HDF5 file


async def test_an_unknown_dataset_is_not_found() -> None:
    with pytest.raises(DatasetNotFoundError):
        await ExportEvidence(InMemoryWeatherStore(), encode_evidence)(
            request("09-01", "10-31", 2000, 2002)
        )


async def test_a_reversed_season_range_is_invalid() -> None:
    with pytest.raises(InvalidArgumentsError):
        await ExportEvidence(store_with_series(), encode_evidence)(
            request("09-01", "10-31", 2002, 2000)
        )


async def test_seasons_outside_the_dataset_are_invalid() -> None:
    with pytest.raises(InvalidArgumentsError, match="no day"):
        await ExportEvidence(store_with_series(), encode_evidence)(
            request("09-01", "10-31", 2010, 2012)
        )


@pytest.mark.parametrize("key", ["dataset_id", "source", "manifest_checksum", "first_season"])
async def test_a_caller_attribute_may_not_overwrite_provenance(key: str) -> None:
    with pytest.raises(InvalidArgumentsError, match=key):
        await ExportEvidence(store_with_series(), encode_evidence)(
            request("09-01", "10-31", 2000, 2002, {key: "forged"})
        )
