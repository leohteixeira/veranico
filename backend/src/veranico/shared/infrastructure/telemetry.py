"""Tracing and structured logs, configured in one place.

Four names keep their signatures from the foundation milestone on, because `main.py`,
`problems.py` and the modules call them: `setup_telemetry`, `tracer`, `shutdown` and
`current_trace_id`. The span and attribute names of the specification (section 15) are the
constants below; modules use the constants, so each name is written once.

Nothing sensitive may reach a span or a log line (no secret, raw client address, message
text or tool payload), so this file records as little as it can by construction:

* The root span `http.request` comes from a small middleware here, not from the ASGI
  instrumentation package. It records the method, the route template, the status code and
  the role, and never a client address, a header, a query string or the raw path.
* A span opened through `tracer()` does not record the exception that crosses it. The
  SDK's default writes the exception message and its stack trace into a span event, and a
  message can quote user input (a validation error does). Only the exception type is kept.
* The log formatter writes the type of an exception and where it was raised, never its
  message, for the same reason.
* The access log of the server, which prints the client address, is silenced, and so is
  the request log of the HTTP client, which prints full URLs with their query strings.

Before `configure` runs, and after `shutdown`, the tracer records nothing and
`current_trace_id` returns `None`.
"""

import json
import logging
import re
import sys
import traceback
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal, TextIO

from fastapi import FastAPI
from opentelemetry import context as context_api
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Link, SpanKind, Status, StatusCode
from opentelemetry.util import types
from opentelemetry.util._decorator import _agnosticcontextmanager
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from veranico.shared.infrastructure.settings import Settings

Role = Literal["api", "carrier"]

# Span names (SPEC 15, literal). A tool span is `tool.<name>`: build it with `tool_span_name`.
SPAN_HTTP_REQUEST: Final = "http.request"
SPAN_AGENT_TURN: Final = "agent.turn"
SPAN_LLM_CALL: Final = "llm.call"
SPAN_TOOL_PREFIX: Final = "tool."
SPAN_OUTBOX_DELIVER: Final = "outbox.deliver"
SPAN_CLIMATE_INGEST: Final = "climate.ingest"

# http.request
ATTR_HTTP_METHOD: Final = "http.request.method"
ATTR_HTTP_ROUTE: Final = "http.route"  # the route template, never the raw path
ATTR_HTTP_STATUS_CODE: Final = "http.response.status_code"
ATTR_ROLE: Final = "veranico.role"
# agent.turn
ATTR_AGENT_CONVERSATION_ID: Final = "agent.conversation_id"
ATTR_AGENT_PROMPT_VERSION: Final = "agent.prompt_version"
ATTR_AGENT_STOP_REASON: Final = "agent.stop_reason"
ATTR_AGENT_TOOL_CALLS: Final = "agent.tool_calls"
# llm.call
ATTR_LLM_MODEL: Final = "llm.model"
ATTR_LLM_INPUT_TOKENS: Final = "llm.input_tokens"
ATTR_LLM_OUTPUT_TOKENS: Final = "llm.output_tokens"
ATTR_LLM_STOP_REASON: Final = "llm.stop_reason"
ATTR_LLM_LATENCY_MS: Final = "llm.latency_ms"
# Integer micro-dollars, from `AccessFacade.cost_of` and nowhere else.
ATTR_LLM_COST_USD_MICROS: Final = "llm.cost_usd_micros"
# tool.<name>
ATTR_TOOL_STATUS: Final = "tool.status"  # "ok" or "error"
ATTR_TOOL_DURATION_MS: Final = "tool.duration_ms"
ATTR_TOOL_ERROR_CODE: Final = "tool.error_code"
# outbox.deliver
ATTR_OUTBOX_EVENT_ID: Final = "outbox.event_id"
ATTR_OUTBOX_ATTEMPT: Final = "outbox.attempt"
ATTR_OUTBOX_STATUS_CODE: Final = "outbox.status_code"
ATTR_OUTBOX_ERROR_CODE: Final = "outbox.error_code"
ATTR_OUTBOX_DELIVERED: Final = "outbox.delivered"
# climate.ingest
ATTR_CLIMATE_DATASET_ID: Final = "climate.dataset_id"
ATTR_CLIMATE_YEARS_FETCHED: Final = "climate.years_fetched"
ATTR_CLIMATE_ATTEMPTS: Final = "climate.attempts"
# Any span an exception crossed: the exception's class name.
ATTR_ERROR_TYPE: Final = "error.type"

# Field names Cloud Logging reads from a JSON line to link it with a trace.
# Source: https://docs.cloud.google.com/logging/docs/structured-logging, read 2026-11-11.
LOG_FIELD_GCP_TRACE: Final = "logging.googleapis.com/trace"
LOG_FIELD_GCP_SPAN_ID: Final = "logging.googleapis.com/spanId"
LOG_FIELD_GCP_TRACE_SAMPLED: Final = "logging.googleapis.com/trace_sampled"

_provider: TracerProvider | None = None


def tool_span_name(tool: str) -> str:
    """Return the span name of a tool call: `tool.<name>`."""
    return f"{SPAN_TOOL_PREFIX}{tool}"


def setup_telemetry(settings: Settings, app: FastAPI) -> None:
    """Configure tracing and logging for the application. Called once at start."""
    configure(settings, settings.app_role)
    app.add_middleware(_RequestSpan, role=settings.app_role)


def configure(settings: Settings, role: Role, *, exporter: SpanExporter | None = None) -> None:
    """Install the tracer provider and the JSON log handler of this process.

    The exporter comes from the settings (`none`, `otlp`, `cloud_trace`). A test passes
    `exporter` instead, usually the SDK's in-memory exporter; it is then fed synchronously,
    so finished spans are readable as soon as they end. With no exporter spans still get
    identifiers, so log lines and problem documents carry a `trace_id`.

    Calling it again replaces the previous configuration. The provider is kept in this
    module and is not registered as the process-wide OpenTelemetry default, which can be
    set only once: tracers are handed out by `tracer()`.
    """
    global _provider
    shutdown()
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": f"{settings.telemetry.service_name}-{role}",
                "service.version": settings.telemetry.service_version,
                "deployment.environment.name": settings.environment,
            }
        )
    )
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        selected = exporter_for(settings)
        if selected is not None:
            provider.add_span_processor(BatchSpanProcessor(selected))
    _provider = provider
    _configure_logging(role)


def exporter_for(settings: Settings) -> SpanExporter | None:
    """Build the exporter the settings name: Jaeger in development, Cloud Trace in production."""
    kind = settings.telemetry.exporter
    if kind == "none":
        return None
    if kind == "otlp":
        # OTLP over HTTP. The endpoint is the full URL with the signal path, for example
        # `http://jaeger:4318/v1/traces`. Left unset, the exporter reads the standard
        # OTEL_EXPORTER_OTLP_* variables and falls back to localhost:4318.
        return OTLPSpanExporter(endpoint=settings.telemetry.otlp_endpoint)
    # cloud_trace: the project and the credentials come from the runtime service account.
    exporter: SpanExporter = CloudTraceSpanExporter()  # type: ignore[no-untyped-call]  # the package ships no type hints
    return exporter


def tracer(name: str = "veranico") -> trace.Tracer:
    """Return the tracer modules open their spans with.

    The tracer may be kept: it looks the provider up when a span starts, so one obtained
    before `configure` records once telemetry is configured.
    """
    return _Tracer(name)


def shutdown() -> None:
    """Flush and stop the exporter. Called once at exit."""
    global _provider
    provider, _provider = _provider, None
    if provider is not None:
        provider.shutdown()


def current_trace_id() -> str | None:
    """Return the trace id of the current span as hex, or `None` outside a span."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return trace.format_trace_id(span_context.trace_id)


class _Tracer(trace.Tracer):
    """Delegates to the configured provider and keeps exception text out of spans."""

    def __init__(self, name: str) -> None:
        self._name = name

    def _delegate(self) -> trace.Tracer:
        if _provider is None:
            return trace.NoOpTracer()
        return _provider.get_tracer(self._name)

    def start_span(
        self,
        name: str,
        context: context_api.Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: types.Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> trace.Span:
        # The two exception switches are forced off whatever the caller passed: see the
        # module docstring. `start_as_current_span` records the exception type instead.
        return self._delegate().start_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes,
            links=links,
            start_time=start_time,
            record_exception=False,
            set_status_on_exception=False,
        )

    # The decorator the OpenTelemetry API itself declares this method with: the abstract
    # method's return type is its context manager, which also works on async functions.
    @_agnosticcontextmanager
    def start_as_current_span(
        self,
        name: str,
        context: context_api.Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: types.Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> Iterator[trace.Span]:
        with self._delegate().start_as_current_span(
            name,
            context=context,
            kind=kind,
            attributes=attributes,
            links=links,
            start_time=start_time,
            record_exception=False,
            set_status_on_exception=False,
            end_on_exit=end_on_exit,
        ) as span:
            try:
                yield span
            except BaseException as error:
                kind_of_error = type(error).__name__
                span.set_attribute(ATTR_ERROR_TYPE, kind_of_error)
                span.set_status(Status(StatusCode.ERROR, kind_of_error))
                raise


class _RequestSpan:
    """Open the root span `http.request` around every HTTP request."""

    def __init__(self, app: ASGIApp, role: Role) -> None:
        self._app = app
        self._role = role
        self._tracer = tracer()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with self._tracer.start_as_current_span(
            SPAN_HTTP_REQUEST,
            kind=SpanKind.SERVER,
            attributes={ATTR_HTTP_METHOD: scope["method"], ATTR_ROLE: self._role},
        ) as span:
            started = False

            async def send_and_record(message: Message) -> None:
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                    _record_response(span, scope, message["status"])
                await send(message)

            try:
                await self._app(scope, receive, send_and_record)
            except BaseException:
                if not started:
                    # The server answers 500 after this middleware has been left.
                    _record_response(span, scope, 500)
                raise


def _record_response(span: trace.Span, scope: Scope, status: int) -> None:
    span.set_attribute(ATTR_HTTP_STATUS_CODE, status)
    template = _route_template(scope)
    if template is not None:
        span.set_attribute(ATTR_HTTP_ROUTE, template)
    if status >= 500:
        span.set_status(Status(StatusCode.ERROR))


def _route_template(scope: Scope) -> str | None:
    """Return the template of the matched route, such as `/api/v1/quotes/{quote_id}`.

    The router stores the matched route in the scope, and that route knows its path
    relative to the router it was declared on (`/quotes/{quote_id}`). The prefix the router
    was included under is the start of the request path that the route's own pattern does
    not consume; the prefixes of this application (`/api/v1`) are literal text.

    A request that matched no route (a 404, a file of the built frontend) has no template:
    the raw path can carry identifiers and is never recorded.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    pattern = getattr(route, "path_regex", None)
    if not isinstance(template, str) or not isinstance(pattern, re.Pattern):
        return None
    path: str = scope["path"]
    for start, character in enumerate(path):
        if character == "/" and pattern.match(path[start:]):
            return path[:start] + template
    return None


# --- Structured logs ---------------------------------------------------------------------

# Attributes every `logging.LogRecord` has; anything else on a record came from `extra=`.
_RECORD_ATTRIBUTES: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with the identifiers of the active span.

    Fields: `timestamp` (UTC, RFC 3339), `severity`, `logger`, `message`, `role`; inside a
    span also `trace_id`, `span_id` and the three fields Cloud Logging uses to attach the
    line to its trace. Scalar values passed through `extra=` become fields of their own, so
    a caller logs identifiers and counts as fields instead of formatting them into prose.
    An exception is written as its type and the frames it passed, without its message.
    """

    def __init__(self, role: Role) -> None:
        super().__init__()
        self._role = role

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "role": self._role,
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            trace_id = trace.format_trace_id(span_context.trace_id)
            span_id = trace.format_span_id(span_context.span_id)
            entry["trace_id"] = trace_id
            entry["span_id"] = span_id
            entry[LOG_FIELD_GCP_TRACE] = trace_id
            entry[LOG_FIELD_GCP_SPAN_ID] = span_id
            entry[LOG_FIELD_GCP_TRACE_SAMPLED] = span_context.trace_flags.sampled
        for key, value in vars(record).items():
            if key in _RECORD_ATTRIBUTES or key in entry:
                continue
            if value is None or isinstance(value, str | int | float | bool):
                entry[key] = value
        if record.exc_info is not None and record.exc_info[0] is not None:
            entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "frames": [
                    f"{frame.filename}:{frame.lineno} in {frame.name}"
                    for frame in traceback.extract_tb(record.exc_info[2])
                ],
            }
        return json.dumps(entry, ensure_ascii=False)


class _StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever `sys.stdout` is when a record is emitted.

    A handler that kept the stream it was created with would write to a closed file once
    something replaces `sys.stdout` (pytest does, per test).
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, value: TextIO) -> None:
        """Ignored: the stream is always the current `sys.stdout`."""


def _configure_logging(role: Role) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _StdoutHandler)]:
        root.removeHandler(handler)
    handler = _StdoutHandler()
    handler.setFormatter(JsonLogFormatter(role))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # The server installs handlers of its own that print plain text. Its messages go
    # through the JSON handler instead; its access log prints the client address and is
    # dropped (the server is also started with the access log off).
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    # The HTTP client logs every request at INFO with its full URL, and a URL of the
    # geocoding service carries the place name a visitor typed.
    logging.getLogger("httpx").setLevel(logging.WARNING)
