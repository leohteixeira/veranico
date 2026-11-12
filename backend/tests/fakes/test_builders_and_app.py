"""The builders and the test application: what other plans' tests start from."""

from typing import Annotated

import httpx
import numpy as np
from fastapi import APIRouter, Depends, FastAPI

from tests.fakes import builders
from tests.fakes.access import FakeAccessFacade
from tests.fakes.app import build_test_app
from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.http_auth import browser_principal, require_service_identity
from veranico.shared.kernel.errors import InvalidCoverError
from veranico.shared.kernel.ids import PointDataset, parse_dataset_id
from veranico.shared.kernel.principal import Principal


def test_daily_series_is_seeded_synthetic_and_gap_free() -> None:
    first = builders.daily_series(seed=7, first_year=2000, last_year=2003)
    again = builders.daily_series(seed=7, first_year=2000, last_year=2003)
    other = builders.daily_series(seed=8, first_year=2000, last_year=2003)

    assert np.array_equal(first.precipitation_mm, again.precipitation_mm)
    assert not np.array_equal(first.precipitation_mm, other.precipitation_mm)
    assert first.dataset == again.dataset
    assert first.dataset.source == "synthetic"
    assert (first.dataset.kind, first.dataset.region_id) == ("point", None)
    assert first.dataset.days == len(first.dates) == 1461  # four years, one leap day
    assert str(first.dates[0]) == "2000-01-01"
    assert str(first.dates[-1]) == "2003-12-31"
    assert first.precipitation_mm.min() >= 0
    assert first.precipitation_mm.max() > 0
    parsed = parse_dataset_id(first.dataset.dataset_id)
    assert parsed == PointDataset(h3_cell=builders.h3_cell_for(builders.LAT, builders.LON))


def test_region_cube_is_seeded_synthetic_and_has_the_contract_shape() -> None:
    cube = builders.region_cube(seed=1, nx=3, ny=2, first_year=2001, last_year=2001)
    again = builders.region_cube(seed=1, nx=3, ny=2, first_year=2001, last_year=2001)
    area = cube.region

    assert cube.precipitation_mm.shape == (365, 2, 3)
    assert np.array_equal(cube.precipitation_mm, again.precipitation_mm)
    assert area.synthetic is True
    assert (area.nx, area.ny) == (3, 2)
    assert area.south < area.north
    assert area.west < area.east
    assert builders.cube_cell_ref(cube, 1, 2).dataset_id == "cube:sorriso:1:2"
    assert builders.cube_cell_ref(cube, 1, 2).source == "synthetic"


def test_priced_cover_is_deterministic_and_may_carry_a_negative_gap() -> None:
    cover = builders.cover(index_type="dry_spell_above")

    first = builders.priced_cover(cover)
    negative = builders.priced_cover(cover, gap_to_burn_cost_cents=-12_345)

    assert first == builders.priced_cover(cover)
    assert first.simulation.method == "bootstrap"
    assert negative.simulation.gap_to_burn_cost.amount_cents == -12_345
    assert negative.simulation.expected_loss.amount_cents == (
        negative.backtest.burn_cost.amount_cents - 12_345
    )


def test_quote_view_survives_a_json_round_trip() -> None:
    view = builders.quote_view(
        priced=builders.priced_cover(gap_to_burn_cost_cents=-1), label="Fazenda Boa Vista"
    )

    assert type(view).model_validate_json(view.model_dump_json()) == view
    assert view.location.label == "Fazenda Boa Vista"
    assert view.dataset_id == view.priced.backtest.dataset_id
    assert view.location.h3_cell in view.dataset_id
    assert view.audit[0].action.code == "audit.quote_created"


def test_rate_is_a_six_place_string_by_integer_division() -> None:
    assert builders.rate(1, 3) == "0.333333"
    assert builders.rate(2, 1) == "2.000000"
    assert builders.rate(0, 7) == "0.000000"


def routers() -> list[APIRouter]:
    router = APIRouter()

    @router.get("/who")
    async def who(principal: Annotated[Principal, Depends(browser_principal)]) -> Principal:
        return principal

    @router.get("/broken")
    async def broken() -> None:
        raise InvalidCoverError("exit must be below the trigger")

    @router.post("/internal", dependencies=[Depends(require_service_identity)])
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    return [router]


async def call(app: FastAPI, method: str, path: str, **kwargs: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=kwargs)


async def test_build_test_app_mounts_routers_under_the_prefix_with_auth_and_problems() -> None:
    access = FakeAccessFacade()
    app = build_test_app(routers(), access)

    who = await call(app, "GET", "/api/v1/who")
    broken = await call(app, "GET", "/api/v1/broken")
    unprefixed = await call(app, "GET", "/who")

    assert who.status_code == 200
    assert who.json()["workspace_id"] == "ws-1"
    assert "vr_ws=cookie-1" in who.headers["set-cookie"]
    assert access.calls == [("open_workspace", (None,))]
    assert broken.status_code == 422
    assert broken.headers["content-type"] == "application/problem+json"
    assert broken.json()["code"] == "invalid_cover"
    assert unprefixed.status_code == 404


async def test_build_test_app_uses_a_fresh_fake_and_test_settings_by_default() -> None:
    first = build_test_app(routers())
    second = build_test_app(routers())

    one = await call(first, "GET", "/api/v1/who")
    two = await call(second, "GET", "/api/v1/who")
    internal = await call(first, "POST", "/api/v1/internal")

    assert one.json()["workspace_id"] == two.json()["workspace_id"] == "ws-1"  # not shared
    assert internal.status_code == 200  # the service identity check is off in test settings


async def test_build_test_app_takes_settings_to_test_the_service_identity() -> None:
    settings = settings_for_tests(delivery={"internal_auth": "token", "internal_token": "t0ken"})
    app = build_test_app(routers(), settings=settings)

    refused = await call(app, "POST", "/api/v1/internal")
    accepted = await call(app, "POST", "/api/v1/internal", Authorization="Bearer t0ken")

    assert refused.status_code == 403
    assert accepted.status_code == 200
