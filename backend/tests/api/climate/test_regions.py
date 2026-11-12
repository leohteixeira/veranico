"""`GET /api/v1/regions`: public reference data served by the real climate module."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from tests.fakes.app import build_test_app
from tests.fakes.settings import settings_for_tests
from veranico.modules.climate.module import ClimateDeps, build
from veranico.shared.infrastructure.blobs import LocalBlobStore
from veranico.shared.kernel.clock import FixedClock


def offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call: {request.url}")


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    module = build(
        ClimateDeps(
            settings=settings_for_tests(climate={"store_root": tmp_path / "weather"}),
            clock=FixedClock(datetime(2026, 11, 11, tzinfo=UTC)),
            http=httpx.AsyncClient(transport=httpx.MockTransport(offline)),
            blobs=LocalBlobStore(tmp_path / "blobs"),
        )
    )
    return build_test_app(module.routers)


@pytest.mark.req("R-4.1-1", "R-11.2-9")
async def test_regions_need_no_cookie_and_are_three_synthetic_grids_of_20_by_20(
    app: FastAPI,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/regions")  # no cookie, no header

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    regions = response.json()
    assert [region["region_id"] for region in regions] == [
        "sul-de-minas",
        "sorriso",
        "ribeirao-preto",
    ]
    for region in regions:
        assert (region["nx"], region["ny"], region["step_deg"]) == (20, 20, 0.1)
        assert region["synthetic"] is True  # the test store holds no cube, so none is real
        assert set(region) == {
            "region_id",
            "name",
            "crop",
            "north",
            "south",
            "west",
            "east",
            "step_deg",
            "nx",
            "ny",
            "synthetic",
        }
    assert regions[0] | {"name": "Sul de Minas", "crop": "coffee"} == regions[0]
    assert (regions[0]["north"], regions[0]["south"]) == (-20.45, -22.45)
    assert (regions[0]["west"], regions[0]["east"]) == (-46.55, -44.55)
