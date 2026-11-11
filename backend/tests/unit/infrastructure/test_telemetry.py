from fastapi import FastAPI

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure import telemetry


def test_the_four_entry_points_exist_and_do_nothing() -> None:
    assert telemetry.setup_telemetry(settings_for_tests(), FastAPI()) is None  # type: ignore[func-returns-value]  # asserting the no-op
    assert telemetry.shutdown() is None  # type: ignore[func-returns-value]  # asserting the no-op
    assert telemetry.current_trace_id() is None


def test_the_tracer_opens_spans_that_record_nothing() -> None:
    with telemetry.tracer().start_as_current_span("climate.ingest") as span:
        span.set_attribute("climate.attempts", 2)

        assert span.is_recording() is False
        assert span.get_span_context().is_valid is False
