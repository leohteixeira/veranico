import httpx
import pytest
from fastapi import FastAPI

from tests.fakes.settings import settings_for_tests
from veranico.main import create_app
from veranico.shared.infrastructure.settings import Settings

EMULATOR = "127.0.0.1:8580"  # never contacted: the Firestore client connects on first use


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def paths(app: FastAPI) -> set[str]:
    return set(app.openapi()["paths"])


@pytest.mark.parametrize("role", ["api", "carrier"])
@pytest.mark.req("R-11.2-13", "R-11.4-2")
async def test_each_role_answers_200_on_healthz_and_readyz(role: str) -> None:
    app = create_app(settings_for_tests(role, firestore_emulator_host=EMULATOR))  # type: ignore[arg-type]  # parametrized literal

    async with client(app) as http:
        health = await http.get("/healthz")
        ready = await http.get("/readyz")

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert (ready.status_code, ready.json()) == (200, {"status": "ready"})


@pytest.mark.req("R-3-2")
async def test_carrier_role_exposes_no_api_route() -> None:
    app = create_app(settings_for_tests("carrier", firestore_emulator_host=EMULATOR))

    assert not [path for path in paths(app) if path.startswith("/api")]
    assert {"/healthz", "/readyz"} <= paths(app)
    async with client(app) as http:
        assert (await http.get("/api/v1/regions")).status_code == 404


@pytest.mark.req("R-3-2")
async def test_api_role_exposes_no_carrier_route() -> None:
    app = create_app(settings_for_tests("api", firestore_emulator_host=EMULATOR))

    assert not [path for path in paths(app) if path.startswith("/carrier")]
    async with client(app) as http:
        assert (await http.post("/carrier/v1/submissions", json={})).status_code == 404


async def test_carrier_role_builds_with_only_its_own_settings() -> None:
    settings = Settings(
        app_role="carrier",
        firestore_emulator_host=EMULATOR,
        delivery={"webhook_signing_secret": "test-webhook-signing-secret"},  # type: ignore[arg-type]  # pydantic builds the group from a mapping
    )
    assert settings.anthropic_api_key is None
    assert settings.cookie_signing_secret is None

    app = create_app(settings)

    async with client(app) as http:
        assert (await http.get("/healthz")).status_code == 200


async def test_settings_come_from_the_environment_when_none_are_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ROLE", "carrier")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", EMULATOR)
    monkeypatch.setenv("VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET", "test-webhook-signing-secret")

    app = create_app()

    assert app.title == "Veranico mock carrier"
