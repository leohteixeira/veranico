"""Telemetry entry points.

Four names keep their signatures from the foundation milestone on, so `main.py`,
`problems.py` and the modules can call them before telemetry exists: `setup_telemetry`,
`tracer`, `shutdown` and `current_trace_id`. Until the delivery plan fills this file they
do nothing: no exporter is configured and the tracer records nothing.
"""

from fastapi import FastAPI
from opentelemetry import trace

from veranico.shared.infrastructure.settings import Settings


def setup_telemetry(settings: Settings, app: FastAPI) -> None:
    """Configure tracing and logging for the application. Called once at start."""


def tracer(name: str = "veranico") -> trace.Tracer:
    """Return the tracer modules open their spans with."""
    return trace.NoOpTracer()


def shutdown() -> None:
    """Flush and stop the exporter. Called once at exit."""


def current_trace_id() -> str | None:
    """Return the trace id of the current span as hex, or `None` outside a span."""
    return None
