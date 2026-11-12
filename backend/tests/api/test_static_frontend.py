from pathlib import Path

import httpx
import pytest

from tests.fakes.settings import settings_for_tests
from veranico.main import create_app

EMULATOR = "127.0.0.1:8580"  # never contacted: the Firestore client connects on first use
HTML = {"Accept": "text/html"}
NOBODY = "frame-ancestors 'none'"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>Veranico</title>")
    (directory / "assets" / "app.js").write_text("console.log('veranico')")
    return directory


def client(dist: Path, frame_ancestors: list[str], role: str = "api") -> httpx.AsyncClient:
    settings = settings_for_tests(
        role,  # type: ignore[arg-type]  # literal chosen by the test
        firestore_emulator_host=EMULATOR,
        frontend_dist=dist,
        frame_ancestors=frame_ancestors,
    )
    transport = httpx.ASGITransport(app=create_app(settings))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.req("R-17-1")
async def test_built_frontend_is_served_at_the_root(dist: Path) -> None:
    async with client(dist, []) as http:
        index = await http.get("/", headers=HTML)
        asset = await http.get("/assets/app.js")

    assert index.status_code == 200
    assert "<title>Veranico</title>" in index.text
    assert asset.status_code == 200
    assert asset.text == "console.log('veranico')"


@pytest.mark.req("R-12.5-2")
async def test_embed_route_falls_back_to_index_and_names_the_configured_origins(dist: Path) -> None:
    origins = ["http://127.0.0.1:3450", "https://leohteixeira.com"]
    async with client(dist, origins) as http:
        embed = await http.get("/embed/map?region=sorriso&lang=en&theme=light", headers=HTML)

    assert embed.status_code == 200
    assert "<title>Veranico</title>" in embed.text
    assert embed.headers["content-security-policy"] == (
        "frame-ancestors http://127.0.0.1:3450 https://leohteixeira.com"
    )


@pytest.mark.req("R-12.5-2")
async def test_embed_route_may_be_framed_by_nobody_when_no_origin_is_configured(dist: Path) -> None:
    async with client(dist, []) as http:
        embed = await http.get("/embed/map", headers=HTML)

    assert embed.status_code == 200
    assert embed.headers["content-security-policy"] == NOBODY


@pytest.mark.parametrize(
    "path", ["/", "/assets/app.js", "/some/client/route", "/embed", "/embed/map/other", "/healthz"]
)
@pytest.mark.req("R-12.5-2")
async def test_every_other_response_may_be_framed_by_nobody(dist: Path, path: str) -> None:
    async with client(dist, ["http://127.0.0.1:3450"]) as http:
        response = await http.get(path, headers=HTML)

    assert response.headers["content-security-policy"] == NOBODY


async def test_api_routes_win_over_frontend_files_and_keep_the_policy(dist: Path) -> None:
    (dist / "healthz").write_text("a file with the name of a route")
    async with client(dist, ["http://127.0.0.1:3450"]) as http:
        health = await http.get("/healthz")
        # The deployed liveness route must not fall back to `index.html`.
        deployed_health = await http.get("/health", headers=HTML)
        missing = await http.get("/api/v1/does-not-exist")

    assert health.json() == {"status": "ok"}
    assert deployed_health.json() == {"status": "ok"}
    assert missing.status_code == 404
    assert missing.headers["content-security-policy"] == NOBODY


async def test_application_starts_without_a_built_frontend(tmp_path: Path) -> None:
    async with client(tmp_path / "missing", []) as http:
        root = await http.get("/", headers=HTML)
        health = await http.get("/healthz")

    assert root.status_code == 404
    assert root.headers["content-security-policy"] == NOBODY
    assert health.status_code == 200


async def test_carrier_role_serves_no_frontend(dist: Path) -> None:
    async with client(dist, [], role="carrier") as http:
        root = await http.get("/", headers=HTML)

    assert root.status_code == 404
