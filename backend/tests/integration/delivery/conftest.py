"""Fixtures of the delivery integration tests: the real application, observed.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/delivery -m integration -q

`observed` builds the API role through the composition root on the shared emulators, with
the scripted model client, and captures what leaves it: every finished span (the SDK's
in-memory exporter) and every log line, rendered by the JSON formatter of the running
service. Each run writes under fresh identifiers and clears nothing.
"""

import dataclasses
import logging
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.fakes.settings import settings_for_tests
from veranico.bootstrap import Container, build_container
from veranico.main import create_app
from veranico.shared.infrastructure import telemetry
from veranico.shared.infrastructure.settings import Settings

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
STORAGE_HOST = os.environ.get("STORAGE_EMULATOR_HOST", "http://127.0.0.1:8590")
CLIENT_ADDRESS = "203.0.113.77"  # the socket peer of every request (TEST-NET-3)


class _Lines(logging.Handler):
    """Keeps every record as the line the service would write."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(telemetry.JsonLogFormatter("api"))
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@dataclasses.dataclass(frozen=True)
class Observed:
    client: httpx.AsyncClient
    settings: Settings
    container: Container
    _exporter: InMemorySpanExporter
    _logs: _Lines

    @property
    def spans(self) -> tuple[ReadableSpan, ...]:
        return self._exporter.get_finished_spans()

    @property
    def log_lines(self) -> list[str]:
        return list(self._logs.lines)


def _require_listening(name: str, address: str) -> None:
    host, _, port = address.removeprefix("http://").partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the {name} emulator is not listening on {address}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )


@pytest.fixture
async def observed(tmp_path: Path) -> AsyncIterator[Observed]:
    _require_listening("Firestore", FIRESTORE_HOST)
    _require_listening("Cloud Storage", STORAGE_HOST)
    settings = settings_for_tests(
        "api",
        firestore_emulator_host=FIRESTORE_HOST,
        storage_emulator_host=STORAGE_HOST,
        data_root=tmp_path / "data",
        climate={"store_root": tmp_path / "weather"},
    )
    container = build_container(settings)
    app = create_app(container=container)
    exporter = InMemorySpanExporter()
    telemetry.configure(settings, "api", exporter=exporter)

    # Levels and silenced loggers exactly as in a running service; `shutdown` undoes it.
    telemetry.configure_logging("api")
    root = logging.getLogger()
    logs = _Lines()
    root.addHandler(logs)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(
                app=app, raise_app_exceptions=False, client=(CLIENT_ADDRESS, 4711)
            )
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                yield Observed(
                    client=c, settings=settings, container=container, _exporter=exporter, _logs=logs
                )
    finally:
        root.removeHandler(logs)
        telemetry.shutdown()
