"""The Open-Meteo archive client against answers recorded from the real API."""

import random
from typing import Any

import httpx
import numpy as np
import pytest

from tests.unit.climate.replay import load, replaying
from veranico.modules.climate.contracts import GridPoint
from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.validation import validate_daily
from veranico.modules.climate.infrastructure.open_meteo import OpenMeteoArchive, SourceRejectedError
from veranico.shared.infrastructure.settings import ClimateSettings

RECORDING = "open_meteo/brasilia_2020_2021.json"
REQUESTED = (-15.03, -47.93)


async def no_sleep(seconds: float) -> None:
    raise AssertionError("a successful request must not wait")


def archive(http: httpx.AsyncClient) -> OpenMeteoArchive:
    return OpenMeteoArchive(http, ClimateSettings(), rng=random.Random(0), sleep=no_sleep)


def serving(body: dict[str, Any], status: int = 200) -> tuple[httpx.AsyncClient, list[httpx.URL]]:
    """A client that answers every request with one body and keeps the URLs it was asked."""
    asked: list[httpx.URL] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), asked


def day(fetched_dates: np.ndarray, iso: str) -> int:
    return int(np.flatnonzero(fetched_dates == np.datetime64(iso))[0])


@pytest.mark.req("R-4-1")
async def test_a_recording_parses_to_its_dates_and_hand_checked_values() -> None:
    replay = replaying(RECORDING)

    fetched = await archive(replay.client()).fetch(*REQUESTED, 2020, 2021)

    assert fetched.dates.dtype == np.dtype("datetime64[D]")
    assert fetched.precipitation_mm.dtype == np.float64
    assert fetched.dates[0] == np.datetime64("2020-01-01")
    assert fetched.dates[-1] == np.datetime64("2021-12-31")
    assert len(fetched.dates) == 731  # 2020 is a leap year
    # Read by eye from the recording.
    assert fetched.precipitation_mm[day(fetched.dates, "2020-01-01")] == 3.2
    assert fetched.precipitation_mm[day(fetched.dates, "2020-02-29")] == 15.7
    assert fetched.precipitation_mm[day(fetched.dates, "2020-07-15")] == 0.0
    assert fetched.precipitation_mm[day(fetched.dates, "2021-12-31")] == 14.2
    assert validate_daily(fetched.dates, fetched.precipitation_mm) == 0
    assert fetched.attempts == 1
    assert len(replay.calls) == 1


@pytest.mark.req("R-4.2-1")
async def test_the_returned_grid_point_is_reported_not_the_requested_one() -> None:
    fetched = await archive(replaying(RECORDING).client()).fetch(*REQUESTED, 2020, 2021)

    # The 0.25 degree ERA5 grid point, about 8 km from the requested point.
    assert fetched.grid_point == GridPoint(lat=-15.0, lon=-48.0)
    assert (fetched.grid_point.lat, fetched.grid_point.lon) != REQUESTED


@pytest.mark.req("R-4-1")
async def test_the_request_asks_only_for_the_daily_precipitation_sum_by_local_day() -> None:
    replay = replaying(RECORDING)

    fetched = await archive(replay.client()).fetch(*REQUESTED, 2020, 2021)

    asked = httpx.URL(replay.calls[0])
    assert asked.host == "archive-api.open-meteo.com"
    assert asked.path == "/v1/archive"
    assert dict(asked.params) == {
        "latitude": "-15.03",
        "longitude": "-47.93",
        "daily": "precipitation_sum",
        "models": "era5",
        "timezone": "auto",
        "start_date": "2020-01-01",
        "end_date": "2021-12-31",
    }
    assert fetched.request == {
        "url": "https://archive-api.open-meteo.com/v1/archive",
        "latitude": "-15.03",
        "longitude": "-47.93",
        "daily": "precipitation_sum",
        "models": "era5",
        "timezone": "auto",
    }


async def test_missing_values_become_nan() -> None:
    # Recorded with `models=era5_land`, for which Open-Meteo has no precipitation: all null.
    [recording] = load("open_meteo/era5_land_nulls_2020_01.json").values()
    assert recording["body"]["daily"]["precipitation_sum"] == [None] * 5
    http, _ = serving(recording["body"])

    fetched = await archive(http).fetch(*REQUESTED, 2020, 2020)

    assert len(fetched.dates) == 5
    assert np.isnan(fetched.precipitation_mm).all()


async def test_a_long_range_is_asked_in_blocks_of_ten_years_and_joined_in_order() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        start, end = request.url.params["start_date"], request.url.params["end_date"]
        after = np.datetime64(end) + np.timedelta64(1, "D")
        days = np.arange(start, after, dtype="datetime64[D]")
        return httpx.Response(
            200,
            json={
                "latitude": -15.0,
                "longitude": -47.9,
                "daily_units": {"time": "iso8601", "precipitation_sum": "mm"},
                "daily": {"time": [str(d) for d in days], "precipitation_sum": [1.5] * len(days)},
            },
        )

    asked: list[tuple[str, str]] = []

    def recording_handle(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.params["start_date"], request.url.params["end_date"]))
        return handle(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(recording_handle))

    fetched = await archive(http).fetch(*REQUESTED, 1950, 1975)

    assert asked == [
        ("1950-01-01", "1959-12-31"),
        ("1960-01-01", "1969-12-31"),
        ("1970-01-01", "1975-12-31"),
    ]
    assert fetched.dates[0] == np.datetime64("1950-01-01")
    assert fetched.dates[-1] == np.datetime64("1975-12-31")
    assert validate_daily(fetched.dates, fetched.precipitation_mm) == 0  # no gap, no duplicate
    assert fetched.attempts == 3


async def test_blocks_from_two_grid_cells_are_refused() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        first_block = request.url.params["start_date"] == "1950-01-01"
        return httpx.Response(
            200,
            json={
                "latitude": -15.0 if first_block else -15.1,
                "longitude": -47.9,
                "daily_units": {"precipitation_sum": "mm"},
                "daily": {"time": ["1950-01-01"], "precipitation_sum": [0.0]},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))

    with pytest.raises(WeatherDataError, match="two grid cells"):
        await archive(http).fetch(*REQUESTED, 1950, 1965)


async def test_another_unit_than_millimetres_is_refused() -> None:
    [recording] = load(RECORDING).values()
    body = {**recording["body"], "daily_units": {"time": "iso8601", "precipitation_sum": "inch"}}
    http, _ = serving(body)

    with pytest.raises(WeatherDataError, match="unit"):
        await archive(http).fetch(*REQUESTED, 2020, 2021)


async def test_an_answer_without_the_variable_is_refused() -> None:
    http, _ = serving({"latitude": -15.0, "longitude": -47.9, "daily": {"time": []}})

    with pytest.raises(WeatherDataError, match="shape"):
        await archive(http).fetch(*REQUESTED, 2020, 2021)


async def test_a_rejected_request_is_not_a_client_facing_error() -> None:
    # The recorded answer to an invalid `models` value: HTTP 400 with `{"error": true}`.
    [recording] = load("open_meteo/invalid_model_400.json").values()
    assert recording["status"] == 400
    http, asked = serving(recording["body"], status=400)

    with pytest.raises(SourceRejectedError, match="400"):
        await archive(http).fetch(*REQUESTED, 2020, 2021)

    assert len(asked) == 1
