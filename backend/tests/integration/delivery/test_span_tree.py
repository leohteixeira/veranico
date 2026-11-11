"""The span tree of SPEC 15, exported through the in-memory exporter.

What runs today, and what waits:

* Proven on the real application: the root span of a request, and the `trace_id` of a
  problem document being the trace of that span.
* Proven on the telemetry layer with a stand-in emitter (not the assistant): spans opened
  inside a streaming response nest under `http.request` exactly as SPEC 15 draws them,
  every span ends, and a failing tool span keeps its error code.
* Proven on the real application with the scripted model client: the tree of a chat turn
  (`agent.turn`, two `llm.call`, two `tool.<name>`, `climate.ingest` under the tool that
  caused it), the cost of each model call against a value computed by hand, and
  `outbox.deliver` under the request of the queue.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, format_trace_id
from starlette.responses import StreamingResponse

from tests.fakes.settings import settings_for_tests
from tests.integration.delivery.conftest import Observed, observe
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import ModelCompleted, ModelToolCall
from veranico.modules.assistant.infrastructure.scripted_model import ScriptedModelClient, say
from veranico.shared.infrastructure import telemetry
from veranico.shared.infrastructure.settings import DEFAULT_AGENT_MODEL

pytestmark = pytest.mark.integration

CHAT = {"conversation_id": None, "message": "Coffee farm near Varginha", "locale": "en"}

POINT = (-15.03, -47.93)  # what the model asks for
GRID_POINT = (-15.0, -48.0)  # what the archive answers from
UNGROUNDED_FIGURE = "12,345.67"

# Token counts of the two scripted model calls, and their cost computed by hand from the
# prices of the default model in the settings (micro-dollars per million tokens: input
# 100,000, output 500,000, cache read 10,000, cache write 125,000), rounded up:
#   first:  1200 x 100,000 + 300 x 500,000 + 4000 x 10,000 + 800 x 125,000 = 410,000,000
#           / 1,000,000 = 410 micro-dollars
#   second: 1500 x 100,000 + 77 x 500,000 = 188,500,000 / 1,000,000 = 188.5, rounded up 189
FIRST_CALL = ModelUsage(
    model=DEFAULT_AGENT_MODEL,
    input_tokens=1200,
    output_tokens=300,
    cache_read_tokens=4000,
    cache_write_tokens=800,
)
FIRST_CALL_COST = 410
SECOND_CALL = ModelUsage(model=DEFAULT_AGENT_MODEL, input_tokens=1500, output_tokens=77)
SECOND_CALL_COST = 189


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


def attributes(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def archive(request: httpx.Request) -> httpx.Response:
    """The weather archive, offline: 1 mm of rain on every day of the period asked for."""
    assert request.url.host == "archive-api.open-meteo.com", f"unexpected call: {request.url}"
    first = date.fromisoformat(request.url.params["start_date"])
    last = date.fromisoformat(request.url.params["end_date"])
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    return httpx.Response(
        200,
        json={
            "latitude": GRID_POINT[0],
            "longitude": GRID_POINT[1],
            "utc_offset_seconds": -10800,
            "timezone": "America/Sao_Paulo",
            "daily_units": {"time": "iso8601", "precipitation_sum": "mm"},
            "daily": {
                "time": [day.isoformat() for day in days],
                "precipitation_sum": [1.0] * len(days),
            },
        },
    )


@pytest.mark.req("R-15-1", "R-15-2")
async def test_a_real_chat_turn_emits_the_span_tree_with_the_cost_of_each_call(
    tmp_path: Path,
) -> None:
    """One turn of the real assistant: a model call asking for two tools, then the answer.

    The first tool reaches `climate`, which ingests the point (through the offline archive
    above); the second is refused by its own argument check. The answer states a figure no
    tool returned, so the turn has one ungrounded figure.
    """
    model = ScriptedModelClient(
        [
            (
                ModelToolCall("call-1", "get_weather_history", {"lat": POINT[0], "lon": POINT[1]}),
                ModelToolCall("call-2", "price_cover", {"index_type": "no_such_index"}),
                ModelCompleted(stop="tool_use", usage=FIRST_CALL),
            ),
            say(f"The premium is R$ {UNGROUNDED_FIGURE}.", usage=SECOND_CALL),
        ]
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(archive)) as offline,
        observe(tmp_path, model_client=model, http=offline, climate={"first_year": 2024}) as app,
    ):
        response = await app.client.post("/api/v1/chat", json=CHAT)
        spans = app.spans

    assert response.status_code == 200
    assert "event: done" in response.text
    request, turn = one(spans, "http.request"), one(spans, "agent.turn")
    assert children_of(spans, request) == ["agent.turn"]
    assert children_of(spans, turn) == [
        "llm.call",
        "tool.get_weather_history",
        "tool.price_cover",
        "llm.call",
    ]
    history, refused = one(spans, "tool.get_weather_history"), one(spans, "tool.price_cover")
    assert children_of(spans, history) == ["climate.ingest"]
    assert len({span.context.trace_id for span in spans}) == 1
    assert all(span.end_time is not None for span in spans)

    turn_attributes = dict(turn.attributes or {})
    assert turn_attributes[telemetry.ATTR_AGENT_STOP_REASON] == "end_turn"
    assert turn_attributes[telemetry.ATTR_AGENT_TOOL_CALLS] == 2
    assert turn_attributes[telemetry.ATTR_AGENT_PROMPT_VERSION]
    assert turn_attributes[telemetry.ATTR_AGENT_CONVERSATION_ID]
    # A count. The figure itself is message text and is in no span.
    assert turn_attributes[telemetry.ATTR_AGENT_UNGROUNDED_FIGURES] == 1
    assert all(UNGROUNDED_FIGURE not in span.to_json() for span in spans)

    first, second = (attributes(span) for span in spans if span.name == "llm.call")
    assert first.pop(telemetry.ATTR_LLM_LATENCY_MS) >= 0
    assert second.pop(telemetry.ATTR_LLM_LATENCY_MS) >= 0
    assert first == {
        telemetry.ATTR_LLM_MODEL: DEFAULT_AGENT_MODEL,
        telemetry.ATTR_LLM_INPUT_TOKENS: 1200,
        telemetry.ATTR_LLM_OUTPUT_TOKENS: 300,
        telemetry.ATTR_LLM_STOP_REASON: "tool_use",
        telemetry.ATTR_LLM_COST_USD_MICROS: FIRST_CALL_COST,
    }
    assert second == {
        telemetry.ATTR_LLM_MODEL: DEFAULT_AGENT_MODEL,
        telemetry.ATTR_LLM_INPUT_TOKENS: 1500,
        telemetry.ATTR_LLM_OUTPUT_TOKENS: 77,
        telemetry.ATTR_LLM_STOP_REASON: "end_turn",
        telemetry.ATTR_LLM_COST_USD_MICROS: SECOND_CALL_COST,
    }

    history_attributes = attributes(history)
    assert history_attributes[telemetry.ATTR_TOOL_STATUS] == "ok"
    assert history_attributes[telemetry.ATTR_TOOL_DURATION_MS] >= 0
    assert telemetry.ATTR_TOOL_ERROR_CODE not in history_attributes
    refused_attributes = attributes(refused)
    assert refused_attributes[telemetry.ATTR_TOOL_STATUS] == "error"
    assert refused_attributes[telemetry.ATTR_TOOL_ERROR_CODE] == "invalid_arguments"
    assert refused.status.status_code is StatusCode.UNSET

    ingest = attributes(one(spans, "climate.ingest"))
    assert ingest[telemetry.ATTR_CLIMATE_DATASET_ID].startswith("point:")
    assert ingest[telemetry.ATTR_CLIMATE_YEARS_FETCHED] == 2
    assert ingest[telemetry.ATTR_CLIMATE_ATTEMPTS] == 1


@pytest.mark.req("R-15-1")
async def test_a_delivery_call_emits_outbox_deliver_under_its_request(observed: Observed) -> None:
    """The span of a webhook attempt, on the route the queue calls.

    The event does not exist, so the attempt stops at the lookup: what is proven here is
    that the span is emitted under the request with the event and the attempt number. The
    attributes of a completed attempt are asserted where a carrier answers
    (`tests/api/carriers/test_deliver_route.py`).
    """
    event_id = str(uuid.uuid4())

    response = await observed.client.post(f"/api/v1/internal/outbox/{event_id}/deliver")

    assert response.status_code == 404
    spans = observed.spans
    request, deliver = one(spans, "http.request"), one(spans, "outbox.deliver")
    assert children_of(spans, request) == ["outbox.deliver"]
    attributes = dict(deliver.attributes or {})
    assert attributes[telemetry.ATTR_OUTBOX_EVENT_ID] == event_id
    assert attributes[telemetry.ATTR_OUTBOX_ATTEMPT] == 1
    assert telemetry.ATTR_OUTBOX_DELIVERED not in attributes
    assert attributes[telemetry.ATTR_ERROR_TYPE] == "NotFoundError"
