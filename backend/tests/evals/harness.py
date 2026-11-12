"""The whole application in one process, for the happy path test and the evaluation suite.

    docker compose -p veranico up -d --wait firestore storage

`application` builds both roles through the composition root (`bootstrap.build_container`
and `main.create_app`) on the shared emulators and enters their lifespans, so the outbox
relay of the API role runs. The two roles and the outside world meet in one HTTP client:

- `http://api.test` is the API role (the relay calls its internal deliver route there);
- `http://carrier.test` is the mock carrier (the signed webhook goes there);
- any other address is answered from recorded answers, each stored with the exact request
  URL that produced it: the files under `fixtures/` here and the geocoding recordings of the
  climate tests. A request without a recording is refused as a connection error and listed
  in `Application.unrecorded`, so nothing here reaches the network.

With `any_place_name` the geocoder is answered by place name instead of by exact URL, without
regard to case or accents, and a name nobody recorded gets the geocoder's "nothing matches"
answer. A real model words its searches freely, so the evaluation suite needs that.

Weather comes from cubes installed by `install_synthetic_cubes`: generated, seeded data that
the application labels `synthetic`. Nothing measured on them is real weather history.

Every application keeps its documents in a Firestore project of its own, named at random, so
the visitor allowance and the spend ledger start empty and nothing is cleared.
"""

import contextlib
import json
import os
import socket
import subprocess
import sys
import unicodedata
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from tests.fakes.settings import settings_for_tests
from veranico.bootstrap import Container, build_container
from veranico.main import create_app
from veranico.shared.infrastructure.settings import Settings

BACKEND = Path(__file__).resolve().parents[2]
RECORDINGS = (
    Path(__file__).resolve().parent / "fixtures",
    BACKEND / "tests" / "unit" / "climate" / "fixtures" / "geocoding",
)
FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
API_HOST = "api.test"
CARRIER_HOST = "carrier.test"
GEOCODING_HOST = "geocoding-api.open-meteo.com"
BROWSER_ADDRESS = "203.0.113.61"  # the socket peer of the browser (TEST-NET-3)
SHOWCASE_REGIONS = ("sul-de-minas", "sorriso", "ribeirao-preto")
CUBE_SEED = 1
NOTHING_MATCHES: dict[str, Any] = {"generationtime_ms": 0.0}  # the geocoder's empty answer

ModelFactory = Callable[[Settings], object]


class EmulatorDownError(RuntimeError):
    """An emulator the application needs is not listening."""


def require_emulators() -> None:
    for name, address in (("Firestore", FIRESTORE_HOST), ("Cloud Storage", STORAGE_HOST)):
        host, _, port = address.removeprefix("http://").partition(":")
        try:
            socket.create_connection((host, int(port)), timeout=2).close()
        except OSError as error:
            raise EmulatorDownError(
                f"the {name} emulator is not listening on {address}: "
                "run `docker compose -p veranico up -d --wait firestore storage`"
            ) from error


def install_synthetic_cubes(root: Path, regions: Sequence[str] = SHOWCASE_REGIONS) -> None:
    """Install a generated cube of each region under `root` with plan 01's build script."""
    environment = {**os.environ, "VERANICO_CLIMATE__STORE_ROOT": str(root)}
    for region in regions:
        subprocess.run(
            [
                sys.executable,
                "scripts/build_cube.py",
                "--region",
                region,
                "--synthetic",
                "--seed",
                str(CUBE_SEED),
            ],
            cwd=BACKEND,
            env=environment,
            check=True,
            capture_output=True,
            timeout=120,
        )


def recordings() -> dict[str, dict[str, Any]]:
    """Every recorded answer, by request URL."""
    found = {}
    for directory in RECORDINGS:
        for path in sorted(directory.rglob("*.json")):
            recording = json.loads(path.read_text(encoding="utf-8"))
            found[recording["request"]["url"]] = recording
    return found


def plain_name(name: str) -> str:
    """A place name without case, accents or surrounding space."""
    decomposed = unicodedata.normalize("NFKD", name.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class _Network(httpx.AsyncBaseTransport):
    """Routes a request to a role by host and answers the rest from the recordings."""

    def __init__(self, recorded: dict[str, dict[str, Any]], *, any_place_name: bool) -> None:
        self.roles: dict[str, httpx.ASGITransport] = {}
        self.recorded = recorded
        self.unrecorded: list[str] = []
        self._places: dict[str, dict[str, Any]] | None = None
        if any_place_name:
            self._places = {
                plain_name(httpx.URL(url).params["name"]): recording
                for url, recording in recorded.items()
                if httpx.URL(url).host == GEOCODING_HOST
            }

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        role = self.roles.get(request.url.host)
        if role is not None:
            return await role.handle_async_request(request)
        if self._places is not None and request.url.host == GEOCODING_HOST:
            place = self._places.get(plain_name(request.url.params.get("name", "")))
            return httpx.Response(200, json=place["body"] if place else NOTHING_MATCHES)
        url = str(request.url)
        recording = self.recorded.get(url)
        if recording is None or recording["request"]["method"] != request.method:
            self.unrecorded.append(f"{request.method} {url}")
            raise httpx.ConnectError(f"no recording for {request.method} {url}", request=request)
        return httpx.Response(recording["status"], json=recording["body"])


@dataclass
class Application:
    api: FastAPI
    settings: Settings
    container: Container
    model_client: object | None  # what `model_client` or `model_factory` gave
    unrecorded: list[str]  # outside requests that had no recording
    _stack: contextlib.AsyncExitStack = field(repr=False)

    async def browser(self) -> httpx.AsyncClient:
        """A browser of its own: an empty cookie jar. HTTPS: the workspace cookie is `Secure`."""
        transport = httpx.ASGITransport(app=self.api, client=(BROWSER_ADDRESS, 4711))
        return await self._stack.enter_async_context(
            httpx.AsyncClient(transport=transport, base_url=f"https://{API_HOST}")
        )


@contextlib.asynccontextmanager
async def application(
    tmp_path: Path,
    weather_root: Path,
    *,
    model_client: object | None = None,
    model_factory: ModelFactory | None = None,
    any_place_name: bool = False,
    **overrides: Any,
) -> AsyncIterator[Application]:
    """Both roles, running.

    `model_client` replaces the client the `assistant` settings name; `model_factory` builds
    it from the settings of this application instead. `overrides` go to the API role's
    settings.
    """
    require_emulators()
    shared = {
        "firestore_emulator_host": FIRESTORE_HOST,
        "storage_emulator_host": STORAGE_HOST,
        "firestore_project": f"veranico-flow-{uuid.uuid4().hex[:12]}",
    }
    settings = settings_for_tests(
        "api",
        **shared,
        data_root=tmp_path / "data",
        climate={"store_root": weather_root, "attempts": 1},
        delivery={
            "internal_base_url": f"http://{API_HOST}",
            "carrier_base_url": f"http://{CARRIER_HOST}",
            "relay_poll_interval_seconds": 0.05,
            "relay_backoff_base_seconds": 0.05,
            "relay_backoff_cap_seconds": 0.2,
        },
        **overrides,
    )
    if model_factory is not None:
        model_client = model_factory(settings)
    network = _Network(recordings(), any_place_name=any_place_name)
    async with contextlib.AsyncExitStack() as stack:
        http = await stack.enter_async_context(httpx.AsyncClient(transport=network))
        carrier = create_app(
            container=build_container(settings_for_tests("carrier", **shared), http=http)
        )
        container = build_container(settings, model_client=model_client, http=http)
        api = create_app(container=container)
        network.roles[CARRIER_HOST] = httpx.ASGITransport(app=carrier)
        network.roles[API_HOST] = httpx.ASGITransport(app=api)
        await stack.enter_async_context(carrier.router.lifespan_context(carrier))
        # Entered last, so left first: the relay stops before the carrier goes away.
        await stack.enter_async_context(api.router.lifespan_context(api))
        yield Application(
            api=api,
            settings=settings,
            container=container,
            model_client=model_client,
            unrecorded=network.unrecorded,
            _stack=stack,
        )
