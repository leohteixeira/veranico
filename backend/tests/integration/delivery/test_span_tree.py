"""The span tree of SPEC 15, exported through the in-memory exporter.

What runs today, and what waits:

* Proven on the real application: the root span of a request, and the `trace_id` of a
  problem document being the trace of that span.
* Proven on the telemetry layer with a stand-in emitter (not the assistant): spans opened
  inside a streaming response nest under `http.request` exactly as SPEC 15 draws them,
  every span ends, and a failing tool span keeps its error code.
* Open until the modules emit their spans: the same tree from a real chat turn with the
  scripted model client, the hand-computed cost on `llm.call` (plan 06), `outbox.deliver`
  (plans 03 and 04) and `climate.ingest` (plan 01). `test_a_real_chat_turn_emits_agent_turn`
  is the marker: it is expected to fail today and turns into a failure the day the
  assistant emits `agent.turn`, which is when the full assertions replace it.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, format_trace_id
from starlette.responses import StreamingResponse

from tests.fakes.settings import settings_for_tests
from tests.integration.delivery.conftest import Observed
from veranico.shared.infrastructure import telemetry

pytestmark = pytest.mark.integration

CHAT = {"conversation_id": None, "message": "Coffee farm near Varginha", "locale": "en"}


def children_of(spans: tuple[ReadableSpan, ...], parent: ReadableSpan) -> list[str]:
    """Names of the direct children of a span, in the order they ended."""
    return [
        span.name
        for span in spans
        if span.parent is not None and span.parent.span_id == parent.context.span_id
    ]


def one(spans: tuple[ReadableSpan, ...], name: str) -> ReadableSpan:
    (span,) = (span for span in spans if span.name == name)
    return span


async def test_every_request_of_the_real_application_has_one_root_span(
    observed: Observed,
) -> None:
    response = await observed.client.get("/healthz")

    assert response.status_code == 200
    (span,) = observed.spans
    assert span.name == "http.request"
    assert span.parent is None
    assert span.end_time is not None
    assert dict(span.attributes or {}) == {
        telemetry.ATTR_HTTP_METHOD: "GET",
        telemetry.ATTR_HTTP_ROUTE: "/healthz",
        telemetry.ATTR_HTTP_STATUS_CODE: 200,
        telemetry.ATTR_ROLE: "api",
    }


@pytest.mark.req("R-11-2")
async def test_a_problem_document_carries_the_trace_id_of_its_request_span(
    observed: Observed,
) -> None:
    # No region has this identifier whether the route is a stub (501) or real (404):
    # either way the answer is a problem document.
    response = await observed.client.get(
        "/api/v1/regions/no-such-region/cells",
        params={
            "metric": "trigger_frequency",
            "index_type": "rainfall_below",
            "window_start": "09-01",
            "window_end": "10-31",
            "trigger": 100,
            "exit": 20,
        },
    )

    assert response.status_code >= 400
    assert response.headers["content-type"] == "application/problem+json"
    (span,) = observed.spans
    assert response.json()["trace_id"] == format_trace_id(span.context.trace_id)
    attributes = dict(span.attributes or {})
    assert attributes[telemetry.ATTR_HTTP_STATUS_CODE] == response.status_code
    assert attributes[telemetry.ATTR_HTTP_ROUTE] == "/api/v1/regions/{id}/cells"


async def test_spans_opened_inside_a_stream_nest_under_the_request_span() -> None:
    """The mechanism the chat stream relies on, with a stand-in for the agent loop.

    The response body is produced after the handler returned, as server-sent events are.
    The spans opened while it is produced must still hang under `http.request`, which
    must stay open until the stream ends.
    """
    tracer = telemetry.tracer()

    async def turn() -> AsyncIterator[bytes]:
        with tracer.start_as_current_span(telemetry.SPAN_AGENT_TURN) as agent:
            with tracer.start_as_current_span(telemetry.SPAN_LLM_CALL):
                yield b"event: started\n\n"
            with tracer.start_as_current_span(telemetry.tool_span_name("resolve_location")) as ok:
                ok.set_attribute(telemetry.ATTR_TOOL_STATUS, "ok")
                yield b"event: tool_finished\n\n"
            with tracer.start_as_current_span(telemetry.tool_span_name("price_cover")) as failed:
                failed.set_attribute(telemetry.ATTR_TOOL_STATUS, "error")
                failed.set_attribute(telemetry.ATTR_TOOL_ERROR_CODE, "invalid_cover")
                yield b"event: tool_finished\n\n"
            with tracer.start_as_current_span(telemetry.SPAN_LLM_CALL):
                yield b"event: done\n\n"
            agent.set_attribute(telemetry.ATTR_AGENT_TOOL_CALLS, 2)

    app = FastAPI()

    @app.post("/api/v1/chat")
    async def chat() -> StreamingResponse:
        return StreamingResponse(turn(), media_type="text/event-stream")

    settings = settings_for_tests()
    telemetry.setup_telemetry(settings, app)
    exporter = InMemorySpanExporter()
    telemetry.configure(settings, "api", exporter=exporter)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/v1/chat")
    finally:
        telemetry.shutdown()

    assert response.text.count("event:") == 4
    spans = exporter.get_finished_spans()
    request, agent_turn = one(spans, "http.request"), one(spans, "agent.turn")
    assert children_of(spans, request) == ["agent.turn"]
    assert children_of(spans, agent_turn) == [
        "llm.call",
        "tool.resolve_location",
        "tool.price_cover",
        "llm.call",
    ]
    assert len(spans) == 6
    assert all(span.end_time is not None for span in spans)
    assert len({span.context.trace_id for span in spans}) == 1
    assert spans[-1] is request  # the root ends last, after the whole stream
    failed_tool = one(spans, "tool.price_cover")
    assert dict(failed_tool.attributes or {})[telemetry.ATTR_TOOL_ERROR_CODE] == "invalid_cover"
    # A tool error is an answer to the model, not an exception: the span is not an error.
    assert failed_tool.status.status_code is StatusCode.UNSET


# The only test here that carries the two requirement identifiers: the traceability
# matrix must not show the span tree or the cost as proven before a real turn proves them.
@pytest.mark.req("R-15-1", "R-15-2")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "open: the assistant module (plan 06) does not emit agent.turn yet. When it does, "
        "this marker fails and is replaced by the scripted turn with two tool calls, the "
        "hand-computed llm.call cost, outbox.deliver and climate.ingest."
    ),
)
async def test_a_real_chat_turn_emits_agent_turn(observed: Observed) -> None:
    response = await observed.client.post("/api/v1/chat", json=CHAT)

    spans = observed.spans
    request = one(spans, "http.request")
    assert children_of(spans, request) == ["agent.turn"], response.status_code
    turn_children = children_of(spans, one(spans, "agent.turn"))
    assert "llm.call" in turn_children
