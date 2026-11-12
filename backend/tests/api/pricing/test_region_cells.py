"""`GET /api/v1/regions/{id}/cells`: public reference data, called without a cookie."""

import httpx
import pytest

from tests.fakes import builders
from tests.fakes.app import build_test_app
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.pricing.contracts import CellGrid
from veranico.modules.pricing.module import PricingDeps, build

URL = "/api/v1/regions/sorriso/cells"
INDEX: dict[str, str | float] = {
    "index_type": "rainfall_below",
    "window_start": "10-01",
    "window_end": "03-31",
    "trigger": 600,
    "exit": 300,
}


def client() -> httpx.AsyncClient:
    climate = FakeClimateFacade()
    climate.add_cube(builders.region_cube(seed=1, nx=5, ny=4))
    module = build(PricingDeps(settings=settings_for_tests(), climate=climate))
    app = build_test_app(module.routers)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.req("R-11.2-10")
@pytest.mark.req("R-5.8-1")
async def test_trigger_frequency_grid_without_a_cookie() -> None:
    async with client() as http:
        response = await http.get(URL, params={"metric": "trigger_frequency", **INDEX})

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    grid = CellGrid.model_validate(response.json())
    area = builders.region("sorriso", nx=5, ny=4)
    assert (grid.region_id, grid.metric) == ("sorriso", "trigger_frequency")
    assert (grid.nx, grid.ny) == (5, 4)
    assert (grid.north, grid.west, grid.step_deg) == (area.north, area.west, area.step_deg)
    assert len(grid.values) == grid.nx * grid.ny
    assert all(value is not None and 0.0 <= value <= 1.0 for value in grid.values)
    assert grid.seasons == list(range(1950, 2024))
    assert grid.cells_paying is None
    assert grid.suggested_season in grid.seasons
    assert len(grid.breaks) in (2, 6)


@pytest.mark.req("R-11.2-10")
@pytest.mark.req("R-5.8-2")
@pytest.mark.req("R-5.8-4")
async def test_season_anomaly_grid_carries_the_paying_cells() -> None:
    params = {"metric": "season_anomaly", "season": 1987, **INDEX}

    async with client() as http:
        response = await http.get(URL, params=params)

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "season_anomaly"
    assert len(body["values"]) == 20
    assert type(body["cells_paying"]) is int
    assert 0 <= body["cells_paying"] <= 20
    assert len(body["breaks"]) == 7
    assert body["breaks"][3] == 0.0  # symmetric around zero


async def test_season_anomaly_without_a_season_is_an_invalid_arguments_problem() -> None:
    async with client() as http:
        response = await http.get(URL, params={"metric": "season_anomaly", **INDEX})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_arguments"


async def test_wrong_side_exit_is_an_invalid_cover_problem() -> None:
    params = {"metric": "trigger_frequency", **INDEX, "trigger": 300, "exit": 600}

    async with client() as http:
        response = await http.get(URL, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cover"


async def test_unknown_region_is_a_dataset_not_found_problem() -> None:
    async with client() as http:
        response = await http.get(
            "/api/v1/regions/nowhere/cells", params={"metric": "trigger_frequency", **INDEX}
        )

    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


async def test_unknown_metric_is_an_invalid_arguments_problem() -> None:
    async with client() as http:
        response = await http.get(URL, params={"metric": "rainfall", **INDEX})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_arguments"
