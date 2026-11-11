import asyncio
import dataclasses
import os
import signal
import socket
import subprocess
import sys
import time
from types import FrameType

import httpx
import pytest

from tests.fakes.settings import settings_for_tests
from veranico.bootstrap import Container, build_container
from veranico.main import create_app
from veranico.modules.assistant import module as assistant_module
from veranico.modules.climate import module as climate_module
from veranico.modules.quoting import module as quoting_module
from veranico.shared.kernel.ids import EventId

EMULATOR = "127.0.0.1:8580"  # never contacted: the Firestore client connects on first use


def api_container() -> Container:
    return build_container(settings_for_tests("api", firestore_emulator_host=EMULATOR))


class RelayLikeDispatcher:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def enqueue(self, event_id: EventId) -> None:
        self._log.append("enqueue")

    async def start(self) -> None:
        self._log.append("start")

    async def stop(self) -> None:
        self._log.append("stop")


class PlainDispatcher:
    async def enqueue(self, event_id: EventId) -> None:
        raise AssertionError("not used")


async def test_dispatcher_with_start_and_stop_is_started_once_and_stopped_once() -> None:
    log: list[str] = []
    container = dataclasses.replace(api_container(), dispatcher=RelayLikeDispatcher(log))
    app = create_app(container=container)

    async with app.router.lifespan_context(app):
        assert log == ["start"]
        log.append("serving")

    assert log == ["start", "serving", "stop"]


async def test_dispatcher_stops_before_the_shared_clients_close() -> None:
    log: list[str] = []
    container = dataclasses.replace(api_container(), dispatcher=RelayLikeDispatcher(log))
    original_aclose = container.http.aclose

    async def recording_aclose() -> None:
        log.append("http closed")
        await original_aclose()

    container.http.aclose = recording_aclose  # type: ignore[method-assign]  # recording the order
    app = create_app(container=container)

    async with app.router.lifespan_context(app):
        pass

    assert log == ["start", "stop", "http closed"]
    assert container.http.is_closed


async def test_dispatcher_without_the_methods_is_left_alone() -> None:
    container = dataclasses.replace(api_container(), dispatcher=PlainDispatcher())
    app = create_app(container=container)

    async with app.router.lifespan_context(app):
        pass


async def test_stub_dispatcher_of_the_foundation_has_neither_method() -> None:
    dispatcher = api_container().dispatcher

    assert not hasattr(dispatcher, "start")
    assert not hasattr(dispatcher, "stop")


async def test_carrier_role_has_no_dispatcher_and_its_lifespan_runs() -> None:
    container = build_container(settings_for_tests("carrier", firestore_emulator_host=EMULATOR))
    app = create_app(container=container)

    assert container.dispatcher is None
    assert [container.access, container.quoting, container.assistant] == [None, None, None]
    async with app.router.lifespan_context(app):
        pass


async def test_a_passed_http_client_is_shared_and_left_open() -> None:
    passed = httpx.AsyncClient()
    container = build_container(
        settings_for_tests("api", firestore_emulator_host=EMULATOR), http=passed
    )
    app = create_app(container=container)

    async with app.router.lifespan_context(app):
        pass

    assert container.http is passed
    assert not passed.is_closed  # the caller that passed it closes it
    await passed.aclose()


async def test_build_container_hands_model_client_and_http_to_the_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    build_assistant = assistant_module.build
    build_climate = climate_module.build
    build_dispatcher = quoting_module.build_dispatcher

    def spy_assistant(deps: assistant_module.AssistantDeps) -> assistant_module.AssistantModule:
        seen["assistant"] = deps
        return build_assistant(deps)

    def spy_climate(deps: climate_module.ClimateDeps) -> climate_module.ClimateModule:
        seen["climate"] = deps
        return build_climate(deps)

    def spy_dispatcher(**kwargs: object) -> object:
        seen["dispatcher"] = kwargs
        return build_dispatcher(**kwargs)  # type: ignore[arg-type]  # passthrough

    monkeypatch.setattr(assistant_module, "build", spy_assistant)
    monkeypatch.setattr(climate_module, "build", spy_climate)
    monkeypatch.setattr(quoting_module, "build_dispatcher", spy_dispatcher)
    model_client = object()
    passed = httpx.AsyncClient()

    container = build_container(
        settings_for_tests("api", firestore_emulator_host=EMULATOR),
        model_client=model_client,
        http=passed,
    )

    assistant_deps = seen["assistant"]
    climate_deps = seen["climate"]
    assert isinstance(assistant_deps, assistant_module.AssistantDeps)
    assert isinstance(climate_deps, climate_module.ClimateDeps)
    assert assistant_deps.model_client is model_client
    assert assistant_deps.shutdown is container.shutdown
    assert climate_deps.http is passed
    assert seen["dispatcher"]["http"] is passed  # type: ignore[index]  # recorded keyword arguments
    assert assistant_deps.climate is container.climate.facade  # type: ignore[union-attr]  # API role
    await passed.aclose()


async def test_model_client_defaults_to_none() -> None:
    seen: list[object] = []
    original = assistant_module.build

    def spy(deps: assistant_module.AssistantDeps) -> assistant_module.AssistantModule:
        seen.append(deps.model_client)
        return original(deps)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(assistant_module, "build", spy)
        api_container()

    assert seen == [None]


@pytest.mark.req("R-3.1-11")
async def test_carrier_catalog_forwarder_asks_the_carriers_facade_each_time() -> None:
    container = api_container()
    captured: list[object] = []
    original = quoting_module.build

    def spy(deps: quoting_module.QuotingDeps) -> quoting_module.QuotingModule:
        captured.append(deps.carriers)
        return original(deps)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(quoting_module, "build", spy)
        container = api_container()

    catalog = captured[0]
    # The stub carriers facade behind the forwarder raises until plan 04 lands.
    with pytest.raises(NotImplementedError):
        catalog.all()  # type: ignore[attr-defined]  # CarrierCatalog port
    with pytest.raises(NotImplementedError):
        catalog.get("carrier-1")  # type: ignore[attr-defined]  # CarrierCatalog port
    assert container.carriers is not None


@pytest.mark.req("R-17-6")
async def test_sigterm_sets_the_shutdown_event_turns_readyz_503_and_reaches_the_server() -> None:
    received: list[int] = []

    def server_handler(signum: int, frame: FrameType | None) -> None:
        received.append(signum)

    before = signal.signal(signal.SIGTERM, server_handler)  # stands in for uvicorn's handler
    try:
        container = api_container()
        app = create_app(container=container)
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as http,
        ):
            assert (await http.get("/readyz")).status_code == 200
            assert not container.shutdown.is_set()

            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(container.shutdown.wait(), timeout=5)

            ready = await http.get("/readyz")
            assert (ready.status_code, ready.json()) == (503, {"status": "shutting_down"})
            assert (await http.get("/healthz")).status_code == 200
            assert received == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is server_handler  # put back at exit
    finally:
        signal.signal(signal.SIGTERM, before)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.req("R-17-6")
def test_uvicorn_exits_cleanly_on_sigterm_with_the_handler_in_front() -> None:
    """The real server: our handler runs first and uvicorn's own shutdown still happens."""
    port = _free_port()
    environment = {
        "PATH": os.environ["PATH"],
        "APP_ROLE": "carrier",
        "FIRESTORE_EMULATOR_HOST": EMULATOR,
        "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET": "test-webhook-signing-secret",
    }
    command = [sys.executable, "-m", "uvicorn", "veranico.main:create_app", "--factory"]
    command += ["--host", "127.0.0.1", "--port", str(port), "--no-access-log"]
    command += ["--timeout-graceful-shutdown", "5"]
    server = subprocess.Popen(
        command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/readyz", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            assert server.poll() is None, server.stdout.read() if server.stdout else ""
            assert time.monotonic() < deadline, "the server did not start"
            time.sleep(0.1)

        server.send_signal(signal.SIGTERM)
        output, _ = server.communicate(timeout=15)
    finally:
        if server.poll() is None:
            server.kill()

    # After its graceful shutdown uvicorn restores the default handler and re-raises the
    # signal it captured, so the process ends as "terminated by SIGTERM".
    assert server.returncode == -signal.SIGTERM, output
    assert "Application shutdown complete" in output
    assert "Traceback" not in output
