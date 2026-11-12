"""`GET /api/v1/weather/seasons`: public reference data, called without a cookie."""

import httpx
import pytest

from tests.fakes import builders
from tests.fakes.app import build_test_app
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.pricing.contracts import SeasonSeries
from veranico.modules.pricing.module import PricingDeps, build

URL = "/api/v1/weather/seasons"
RAINFALL: dict[str, str | float] = {
    "lat": builders.LAT,
    "lon": builders.LON,
    "index_type": "rainfall_below",
    "window_start": "10-01",
    "window_end": "03-31",
    "trigger": 600,
    "exit": 300,
}


def client_and_climate() -> tuple[httpx.AsyncClient, FakeClimateFacade]:
    climate = FakeClimateFacade()
    climate.add_series(builders.daily_series(seed=0))
    module = build(PricingDeps(settings=settings_for_tests(), climate=climate))
    app = build_test_app(module.routers)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, climate


@pytest.mark.req("R-11.2-11")
async def test_returns_the_season_series_of_the_point_without_a_cookie() -> None:
    client, climate = client_and_climate()

    async with client:
        response = await client.get(URL, params=RAINFALL)

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    series = SeasonSeries.model_validate(response.json())
    assert series.dataset_id == builders.point_dataset_for(builders.LAT, builders.LON)
    assert series.index.index_type == "rainfall_below"
    assert (series.index.window.start, series.index.window.end) == ("10-01", "03-31")
    assert (series.index.trigger, series.index.exit) == (600.0, 300.0)
    assert [season.season for season in series.seasons] == list(range(1950, 2024))
    assert series.seasons_excluded == [1949, 2024]
    assert all(season.payout is None for season in series.seasons)
    assert [name for name, _ in climate.calls] == ["ensure_history", "daily_series"]


@pytest.mark.req("R-11.2-11")
async def test_payouts_are_integer_centavos_when_a_limit_is_sent() -> None:
    client, _ = client_and_climate()

    async with client:
        response = await client.get(URL, params={**RAINFALL, "limit_cents": 30_000_000})

    assert response.status_code == 200
    seasons = response.json()["seasons"]
    payouts = [season["payout"] for season in seasons]
    assert all(set(payout) == {"amount_cents", "currency"} for payout in payouts)
    assert all(type(payout["amount_cents"]) is int for payout in payouts)
    assert any(payout["amount_cents"] > 0 for payout in payouts)
    assert any(payout["amount_cents"] == 0 for payout in payouts)
    assert all(0 <= payout["amount_cents"] <= 30_000_000 for payout in payouts)
    # the series is the one the facade gives for the same input
    assert [season["index_value"] for season in seasons] == [
        round(season["index_value"], 1) for season in seasons
    ]


@pytest.mark.req("R-11.2-11")
async def test_dry_spell_index_is_served_from_the_same_flattened_parameters() -> None:
    client, _ = client_and_climate()
    params = {**RAINFALL, "index_type": "dry_spell_above", "trigger": 9, "exit": 18}

    async with client:
        response = await client.get(URL, params=params)

    assert response.status_code == 200
    series = SeasonSeries.model_validate(response.json())
    assert series.index.index_type == "dry_spell_above"
    assert all(season.index_value == int(season.index_value) for season in series.seasons)


@pytest.mark.req("R-5.3-3")
async def test_wrong_side_exit_is_an_invalid_cover_problem_and_loads_no_history() -> None:
    client, climate = client_and_climate()

    async with client:
        response = await client.get(URL, params={**RAINFALL, "trigger": 300, "exit": 600})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_cover"
    assert climate.calls == []


async def test_limit_that_is_not_positive_is_an_invalid_cover_problem() -> None:
    client, _ = client_and_climate()

    async with client:
        response = await client.get(URL, params={**RAINFALL, "limit_cents": 0})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cover"


async def test_missing_index_parameter_is_an_invalid_arguments_problem() -> None:
    client, _ = client_and_climate()
    params = {name: value for name, value in RAINFALL.items() if name != "trigger"}

    async with client:
        response = await client.get(URL, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_arguments"


async def test_point_outside_coverage_is_a_problem_from_climate() -> None:
    client, _ = client_and_climate()

    async with client:
        response = await client.get(URL, params={**RAINFALL, "lat": 48.85, "lon": 2.35})

    assert response.status_code == 422
    assert response.json()["code"] == "outside_coverage"
