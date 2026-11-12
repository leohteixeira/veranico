"""Telemetry configuration and structured logs (SPEC 15)."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure import telemetry
from veranico.shared.infrastructure.problems import install_problem_handlers
from veranico.shared.kernel.errors import NotFoundError

SENTINEL = "sentinel-7f3a9c"


@pytest.fixture(autouse=True)
def _restore_process_state() -> Iterator[None]:
    """Telemetry and logging are process-wide: every test must leave both as it found them."""
    before = _logging_state()
    yield
    telemetry.shutdown()
    assert _logging_state() == before


def _logging_state() -> dict[str, tuple[list[logging.Handler], int, bool]]:
    return {
        name: (list(logger.handlers), logger.level, logger.propagate)
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx")
        for logger in [logging.getLogger(name)]
    }


@pytest.fixture
def spans() -> InMemorySpanExporter:
    """Tracing into memory and JSON logs on standard output, as in a running server."""
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)
    telemetry.configure_logging("api")
    return exporter


def _log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def _attributes(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


# --- Exporter selection ------------------------------------------------------------------


@pytest.mark.req("R-15-4")
def test_no_exporter_is_built_by_default() -> None:
    assert telemetry.exporter_for(settings_for_tests()) is None


@pytest.mark.req("R-15-4")
def test_otlp_setting_builds_the_otlp_exporter_for_the_configured_endpoint() -> None:
    settings = settings_for_tests(
        telemetry={"exporter": "otlp", "otlp_endpoint": "http://jaeger:4318/v1/traces"}
    )

    exporter = telemetry.exporter_for(settings)

    assert isinstance(exporter, OTLPSpanExporter)
    assert exporter._endpoint == "http://jaeger:4318/v1/traces"  # the SDK exposes no getter


@pytest.mark.req("R-15-4")
def test_cloud_trace_setting_builds_the_cloud_trace_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real exporter looks for Google credentials when it is constructed, so only the
    # selection is proven here; the export itself is gate H2.
    built: list[object] = []

    class Recorder:
        def __init__(self) -> None:
            built.append(self)

    monkeypatch.setattr(telemetry, "CloudTraceSpanExporter", Recorder)

    exporter = telemetry.exporter_for(settings_for_tests(telemetry={"exporter": "cloud_trace"}))

    assert built == [exporter]


@pytest.mark.req("R-15-4")
def test_the_resource_names_the_service_per_role_and_its_version() -> None:
    spans = InMemorySpanExporter()
    settings = settings_for_tests(
        "carrier", telemetry={"service_name": "veranico", "service_version": "1.2.3"}
    )
    telemetry.configure(settings, "carrier", exporter=spans)

    with telemetry.tracer().start_as_current_span("outbox.deliver"):
        pass

    resource = spans.get_finished_spans()[0].resource.attributes
    assert resource["service.name"] == "veranico-carrier"
    assert resource["service.version"] == "1.2.3"


# --- Tracer and trace id -----------------------------------------------------------------


def test_current_trace_id_is_none_outside_a_span(spans: InMemorySpanExporter) -> None:
    assert telemetry.current_trace_id() is None


def test_current_trace_id_is_the_hex_id_of_the_active_span(spans: InMemorySpanExporter) -> None:
    with telemetry.tracer().start_as_current_span(telemetry.SPAN_CLIMATE_INGEST):
        inside = telemetry.current_trace_id()

    exported = spans.get_finished_spans()[0]
    assert inside == format(exported.context.trace_id, "032x")
    assert telemetry.current_trace_id() is None


def test_spans_get_a_trace_id_when_no_exporter_is_configured() -> None:
    telemetry.configure(settings_for_tests(), "api")

    with telemetry.tracer().start_as_current_span(telemetry.SPAN_AGENT_TURN):
        trace_id = telemetry.current_trace_id()

    assert trace_id is not None
    assert len(trace_id) == 32


def test_a_tracer_obtained_before_configuration_records_after_it() -> None:
    kept = telemetry.tracer()
    with kept.start_as_current_span("before") as span:
        assert span.is_recording() is False

    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)
    with kept.start_as_current_span("after"):
        pass

    assert [span.name for span in exporter.get_finished_spans()] == ["after"]


def test_after_shutdown_the_tracer_records_nothing(spans: InMemorySpanExporter) -> None:
    telemetry.shutdown()

    with telemetry.tracer().start_as_current_span("late") as span:
        assert span.is_recording() is False
    assert telemetry.current_trace_id() is None


def test_child_spans_share_the_trace_and_point_at_their_parent(
    spans: InMemorySpanExporter,
) -> None:
    with (
        telemetry.tracer().start_as_current_span(telemetry.SPAN_AGENT_TURN),
        telemetry.tracer().start_as_current_span(telemetry.tool_span_name("price_cover")),
    ):
        pass

    child, parent = spans.get_finished_spans()
    assert child.name == "tool.price_cover"
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id
    assert child.context.trace_id == parent.context.trace_id


@pytest.mark.req("R-15-5")
def test_an_exception_crossing_a_span_leaves_its_type_and_never_its_message(
    spans: InMemorySpanExporter,
) -> None:
    # The caller asks for the SDK default on purpose: the switch must not reopen the leak.
    with (
        pytest.raises(ValueError, match=SENTINEL),
        telemetry.tracer().start_as_current_span(
            "tool.resolve_location", record_exception=True, set_status_on_exception=True
        ),
    ):
        raise ValueError(f"input was {SENTINEL}")

    span = spans.get_finished_spans()[0]
    assert span.events == ()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "ValueError"
    assert _attributes(span)[telemetry.ATTR_ERROR_TYPE] == "ValueError"
    assert SENTINEL not in span.to_json()


@pytest.mark.req("R-15-5")
def test_a_manually_ended_span_does_not_record_the_exception_either(
    spans: InMemorySpanExporter,
) -> None:
    with (
        pytest.raises(ValueError, match=SENTINEL),
        telemetry.tracer().start_span("climate.ingest", record_exception=True),
    ):
        raise ValueError(f"input was {SENTINEL}")

    assert SENTINEL not in spans.get_finished_spans()[0].to_json()


# --- http.request ------------------------------------------------------------------------


def _app() -> FastAPI:
    router = APIRouter(prefix="/items")

    @router.get("")
    async def items() -> list[str]:
        return []

    @router.get("/{item_id}")
    async def item(item_id: str) -> dict[str, str | None]:
        return {"trace_id": telemetry.current_trace_id()}

    other = APIRouter()

    @other.get("/missing/{item_id}")
    async def missing(item_id: str) -> None:
        raise NotFoundError()

    @other.get("/broken")
    async def broken() -> None:
        raise RuntimeError(f"failed on {SENTINEL}")

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.include_router(other, prefix="/api/v1")
    telemetry.setup_telemetry(settings_for_tests(), app)
    return app


async def _get(app: FastAPI, url: str, **headers: str) -> httpx.Response:
    transport = httpx.ASGITransport(
        app=app, raise_app_exceptions=False, client=("203.0.113.77", 4711)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(url, headers=headers)


# R-15-1 (the whole span tree) is not marked in this file: the root span alone does not
# prove it. Its marker is on the chat turn test of tests/integration/delivery.
async def test_http_request_span_carries_method_route_template_status_and_role() -> None:
    app = _app()
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    response = await _get(app, "/api/v1/items/Q-ABC123")

    (span,) = exporter.get_finished_spans()
    assert span.name == "http.request"
    assert span.kind is SpanKind.SERVER
    assert span.parent is None
    assert _attributes(span) == {
        telemetry.ATTR_HTTP_METHOD: "GET",
        telemetry.ATTR_HTTP_ROUTE: "/api/v1/items/{item_id}",
        telemetry.ATTR_HTTP_STATUS_CODE: 200,
        telemetry.ATTR_ROLE: "api",
    }
    assert response.json() == {"trace_id": format(span.context.trace_id, "032x")}


@pytest.mark.parametrize(
    ("url", "template"),
    [
        ("/api/v1/items", "/api/v1/items"),
        ("/api/v1/items/items", "/api/v1/items/{item_id}"),  # a value equal to a literal part
        ("/api/v1/missing/Q-ABC123", "/api/v1/missing/{item_id}"),
        ("/healthz", "/healthz"),
    ],
)
async def test_the_route_attribute_is_the_full_template(url: str, template: str) -> None:
    app = _app()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    await _get(app, url)

    (span,) = exporter.get_finished_spans()
    assert _attributes(span)[telemetry.ATTR_HTTP_ROUTE] == template


@pytest.mark.req("R-15-5")
def test_the_http_client_request_log_is_silenced(
    spans: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    # httpx logs "HTTP Request: GET <full URL>" at INFO; a geocoding URL holds a place name.
    logging.getLogger("httpx").info("HTTP Request: GET https://example.test/?name=%s", SENTINEL)

    assert SENTINEL not in capsys.readouterr().out


@pytest.mark.req("R-15-5")
async def test_http_request_span_holds_no_address_header_query_or_raw_path() -> None:
    app = _app()
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    await _get(
        app,
        f"/api/v1/items/path-{SENTINEL}?code=query-{SENTINEL}",
        authorization=f"Bearer key-{SENTINEL}",
        cookie=f"vr_ws=cookie-{SENTINEL}",
        **{"x-forwarded-for": "198.51.100.23"},
    )

    exported = exporter.get_finished_spans()[0].to_json()
    for forbidden in (SENTINEL, "203.0.113.77", "198.51.100.23"):
        assert forbidden not in exported


async def test_a_request_that_matches_no_route_records_no_route_attribute() -> None:
    app = _app()
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    await _get(app, f"/nowhere/{SENTINEL}")

    (span,) = exporter.get_finished_spans()
    assert _attributes(span)[telemetry.ATTR_HTTP_STATUS_CODE] == 404
    assert telemetry.ATTR_HTTP_ROUTE not in _attributes(span)
    assert SENTINEL not in span.to_json()


async def test_a_problem_document_carries_the_trace_id_of_its_request_span() -> None:
    app = _app()
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    response = await _get(app, "/api/v1/missing/Q-ABC123")

    (span,) = exporter.get_finished_spans()
    assert response.status_code == 404
    assert response.json()["trace_id"] == format(span.context.trace_id, "032x")
    assert span.status.status_code is StatusCode.UNSET  # a 4xx is the client's error


@pytest.mark.req("R-15-5")
async def test_an_unhandled_error_marks_the_span_and_leaks_no_message() -> None:
    app = _app()
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)

    response = await _get(app, "/api/v1/broken")

    (span,) = exporter.get_finished_spans()
    assert response.status_code == 500
    assert _attributes(span)[telemetry.ATTR_HTTP_STATUS_CODE] == 500
    assert _attributes(span)[telemetry.ATTR_ERROR_TYPE] == "RuntimeError"
    assert span.status.status_code is StatusCode.ERROR
    assert SENTINEL not in span.to_json()


# --- Structured logs ---------------------------------------------------------------------


@pytest.mark.req("R-15-3")
def test_a_log_record_inside_a_span_carries_that_spans_identifiers(
    spans: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    with telemetry.tracer().start_as_current_span(telemetry.SPAN_OUTBOX_DELIVER):
        logging.getLogger("veranico.carriers").info("delivery attempt recorded")

    span = spans.get_finished_spans()[0]
    trace_id = format(span.context.trace_id, "032x")
    span_id = format(span.context.span_id, "016x")
    (line,) = _log_lines(capsys)
    assert line["trace_id"] == trace_id
    assert line["span_id"] == span_id
    assert line["logging.googleapis.com/trace"] == trace_id
    assert line["logging.googleapis.com/spanId"] == span_id
    assert line["logging.googleapis.com/trace_sampled"] is True


@pytest.mark.req("R-15-3")
def test_log_output_is_one_json_object_per_line_with_the_fixed_fields(
    spans: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    logger = logging.getLogger("veranico.test")
    logger.info("first\nwith a line break")
    logger.warning("second %s", "formatted")

    output = capsys.readouterr().out
    assert output.endswith("\n")
    first, second = (json.loads(line) for line in output.splitlines())
    assert first["message"] == "first\nwith a line break"
    assert {key: second[key] for key in ("severity", "logger", "message", "role")} == {
        "severity": "WARNING",
        "logger": "veranico.test",
        "message": "second formatted",
        "role": "api",
    }
    assert second["timestamp"].endswith("+00:00")
    assert "trace_id" not in second  # logged outside a span


def test_scalar_extra_values_become_fields_and_other_values_are_dropped(
    spans: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    logging.getLogger("veranico.test").info(
        "webhook attempt",
        extra={"event_id": "0193-abc", "attempt": 2, "payload": {"body": SENTINEL}},
    )

    (line,) = _log_lines(capsys)
    assert line["event_id"] == "0193-abc"
    assert line["attempt"] == 2
    assert "payload" not in line


@pytest.mark.req("R-15-5")
def test_a_logged_exception_keeps_its_type_and_frames_but_not_its_message(
    spans: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        raise ValueError(f"input was {SENTINEL}")
    except ValueError:
        logging.getLogger("veranico.test").exception("tool failed")

    output = capsys.readouterr().out
    (line,) = (json.loads(text) for text in output.splitlines())
    assert line["exception"]["type"] == "ValueError"
    assert "test_telemetry.py" in line["exception"]["frames"][0]
    assert SENTINEL not in output


@pytest.mark.req("R-15-5")
def test_the_servers_access_log_is_silenced_and_its_other_messages_are_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    access = logging.getLogger("uvicorn.access")
    server = logging.getLogger("uvicorn.error")
    plain = logging.StreamHandler()
    access.addHandler(plain)  # what the server installs before the application is built
    try:
        telemetry.configure_logging("api")

        access.info('203.0.113.77:4711 - "GET /api/v1/quotes HTTP/1.1" 200')
        server.info("Started server process")

        captured = capsys.readouterr()
        assert "203.0.113.77" not in captured.out + captured.err
        assert [json.loads(line)["message"] for line in captured.out.splitlines()] == [
            "Started server process"
        ]
        telemetry.shutdown()
        assert access.handlers == [plain]
    finally:
        access.removeHandler(plain)


def test_building_an_application_leaves_the_loggers_of_the_process_alone() -> None:
    before = _logging_state()

    _app()
    telemetry.configure(settings_for_tests(), "api", exporter=InMemorySpanExporter())

    assert _logging_state() == before


async def test_logging_is_configured_when_a_server_starts_the_app_and_undone_at_shutdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _logging_state()
    app = _app()
    messages: list[dict[str, Any]] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    logger = logging.getLogger("veranico.test")

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "lifespan.startup.complete":
            logger.info("serving")

    # What a server does first: run the lifespan through the whole middleware stack.
    await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)

    assert [line["message"] for line in _log_lines(capsys)] == ["serving"]
    assert _logging_state() != before
    telemetry.shutdown()
    assert _logging_state() == before
    logger.info("after shutdown")
    assert capsys.readouterr().out == ""
