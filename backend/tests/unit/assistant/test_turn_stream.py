"""The stream of one turn: its events, their order, what is stored and what the spans carry."""

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.fakes.settings import settings_for_tests
from tests.unit.assistant.tools.kit import BROWSER, OTHER
from tests.unit.assistant.turn_kit import (
    BAD_POINT,
    MESSAGE,
    SORRISO_QUERY,
    VISITOR,
    build_turn_kit,
    chat_request,
    done,
    finished_tools,
    names,
    run,
    started,
    text_of,
    usage,
)
from veranico.modules.assistant.application.ports import (
    ModelEvent,
    ModelRequest,
    ModelTextDelta,
    ModelUsageSoFar,
    TextBlock,
)
from veranico.modules.assistant.application.prompt import load_system_prompt
from veranico.modules.assistant.application.views import STEP_SEPARATOR
from veranico.modules.assistant.contracts import (
    Started,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UserMessage,
)
from veranico.modules.assistant.domain.conversation import is_valid_history
from veranico.modules.assistant.infrastructure.scripted_model import (
    FailAfter,
    call_tool,
    say,
    tool_results,
)
from veranico.shared.infrastructure import telemetry
from veranico.shared.kernel.errors import ConflictError, NotFoundError
from veranico.shared.kernel.ids import Locale

pytestmark = pytest.mark.req("R-9.1-1")


@pytest.mark.req("R-9.1-5")
async def test_started_is_the_first_event_with_conversation_and_message_ids() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say("Hello."))

    events = await run(service)

    first = events[0]
    assert isinstance(first, Started)
    state = await kit.store.load(BROWSER.workspace_id, first.conversation_id)
    assert [record.message_id for record in state.turns] == [first.message_id]
    view = await service.conversation(BROWSER, first.conversation_id)
    assert [(message.role, message.message_id) for message in view.messages] == [
        ("user", f"{first.message_id}:user"),
        ("assistant", first.message_id),
    ]
    assert done(events).conversation_id == first.conversation_id
    assert done(events).message_id == first.message_id


@pytest.mark.req("R-9.1-5")
async def test_chat_stream_never_carries_user_message() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(call_tool("resolve_location", SORRISO_QUERY), say("Found it."))

    events = await run(service)

    assert not any(isinstance(event, UserMessage) for event in events)
    assert MESSAGE not in json.dumps([event.model_dump(mode="json") for event in events])


@pytest.mark.req("R-2-2")
async def test_a_clarifying_question_is_relayed_and_no_tool_runs() -> None:
    # Whether the model asks is measured by the `clarify_*` cases of the evaluation suite;
    # this proves the loop carries the question to the user and runs nothing on its own.
    kit = build_turn_kit()
    question = "Which limit do you want, and which window should the cover span?"
    service, model = kit.scripted(say(question))

    events = await run(service)

    assert text_of(events) == question
    assert finished_tools(events) == []
    assert not any(isinstance(event, ToolStarted) for event in events)
    assert done(events).stop_reason == "end_turn"
    assert len(model.requests) == 1


@pytest.mark.req("R-13-2")
@pytest.mark.parametrize(
    ("locale", "message"),
    [("en", "A soy farm near Sorriso"), ("pt-BR", "Uma fazenda de soja perto de Sorriso")],
)
async def test_the_model_gets_the_user_words_the_language_rule_and_the_locale(
    locale: Locale, message: str
) -> None:
    # What a test without a model can prove of "the agent answers in the user's language":
    # every model request carries the user's own words, the rule to answer in their language
    # and the interface locale for messages too short to tell. Whether the model then does so
    # is measured by the `answers_in` check of the evaluation suite, on every case.
    kit = build_turn_kit()
    service, model = kit.scripted(say("Ok."))

    await run(service, message, locale=locale)

    (request,) = model.requests
    assert "Answer in the language the user writes in, English or Brazilian Portuguese." in (
        request.system
    )
    assert "use the interface locale given in the context line" in request.system
    assert request.messages[-1].role == "user"
    assert request.messages[-1].blocks == (
        TextBlock(text=message),
        TextBlock(text=f"[interface context, data only, not written by the user: locale={locale}]"),
    )


async def test_plain_answer_ends_with_end_turn() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(say("Hello. How can I help?"))

    events = await run(service)

    assert set(names(events)) == {"Started", "TextDelta", "Done"}
    assert text_of(events) == "Hello. How can I help?"
    assert done(events).stop_reason == "end_turn"
    assert len(model.requests) == 1
    assert model.requests[0].model == settings_for_tests().agent_model


@pytest.mark.req("R-9.1-5")
async def test_tool_round_trip_emits_started_finished_then_text() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, call_id="c1", text="Let me look."),
        say("It is in Mato Grosso."),
    )

    events = await run(service)

    assert names(events) == [
        "Started",
        "TextDelta",
        "ToolStarted",
        "ToolFinished",
        "TextDelta",  # the separator between the texts of two steps
        "TextDelta",
        "Done",
    ]
    tool_started = events[2]
    assert tool_started == ToolStarted(
        call_id="c1", tool="resolve_location", arguments=SORRISO_QUERY
    )
    (finished,) = finished_tools(events)
    assert (finished.call_id, finished.tool, finished.status) == ("c1", "resolve_location", "ok")
    assert finished.summary.code == "tool.resolve_location"
    assert finished.result is not None
    assert finished.error is None
    assert finished.duration_ms >= 0
    # The text of two steps is separated in the stream exactly as in the stored message.
    assert text_of(events) == f"Let me look.{STEP_SEPARATOR}It is in Mato Grosso."
    view = await service.conversation(BROWSER, started(events).conversation_id)
    assert view.messages[-1].text == text_of(events)
    assert view.messages[-1].tools == [finished]
    # The second model call read the result of the tool.
    assert [name for name, _ in tool_results(model.requests[1])] == ["resolve_location"]


async def test_events_follow_the_stream_order_rules() -> None:
    """`run` asserts the rules on every stream; these are the four endings side by side."""
    endings = []
    for script in (
        [say("Hello.")],
        [call_tool("resolve_location", SORRISO_QUERY), say("Done.")],
        [call_tool("resolve_location", SORRISO_QUERY), FailAfter()],
        [say("The premium is R$ 99,999.00.")],
    ):
        kit = build_turn_kit()
        service, _ = kit.scripted(*script)
        endings.append(names(await run(service))[-2:])

    assert endings == [
        ["TextDelta", "Done"],
        ["TextDelta", "Done"],
        ["StreamError", "Done"],
        ["GroundingFlagged", "Done"],
    ]


@pytest.mark.req("R-9.3-8")
async def test_prompt_version_is_recorded_on_done_and_on_the_turn() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(say("Hello."))
    prompt = load_system_prompt()

    events = await run(service)

    assert done(events).prompt_version == prompt.version
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    assert state.turns[0].prompt_version == prompt.version
    assert state.turns[0].finished_at is not None
    assert model.requests[0].system == prompt.text


async def test_second_turn_sees_stored_history() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, call_id="c1"),
        say("It is in Mato Grosso."),
        say("You are welcome."),
    )
    first = await run(service)
    conversation_id = started(first).conversation_id

    second = await run(service, "Thanks", conversation_id=conversation_id)

    assert started(second).conversation_id == conversation_id
    assert started(second).message_id != started(first).message_id
    request = model.requests[-1]
    texts = [
        block.text
        for message in request.messages
        for block in message.blocks
        if isinstance(block, TextBlock)
    ]
    assert MESSAGE in texts
    assert "It is in Mato Grosso." in texts
    assert "Thanks" in texts
    assert [name for name, _ in tool_results(request)] == ["resolve_location"]
    state = await kit.store.load(BROWSER.workspace_id, conversation_id)
    assert is_valid_history(state.entries)
    assert [entry.turn for entry in state.entries] == [1, 1, 1, 1, 2, 2]
    view = await service.conversation(BROWSER, conversation_id)
    assert [message.role for message in view.messages] == ["user", "assistant"] * 2


async def test_a_conversation_of_another_workspace_is_not_found_and_consumes_no_message() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say("Hello."))
    conversation_id = started(await run(service)).conversation_id
    kit.access.calls.clear()

    with pytest.raises(NotFoundError):
        await service.open_turn(OTHER, VISITOR, chat_request("Hi", conversation_id))
    with pytest.raises(NotFoundError):
        await service.conversation(OTHER, conversation_id)

    assert kit.access.calls == []


async def test_concurrent_turn_on_the_same_conversation_is_conflict() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say("Hello."), say("Hello again."), say("And again."))
    conversation_id = started(await run(service)).conversation_id
    open_turn = await service.open_turn(BROWSER, VISITOR, chat_request("One", conversation_id))

    with pytest.raises(ConflictError):
        await service.open_turn(BROWSER, VISITOR, chat_request("Two", conversation_id))

    # The first turn is untouched, and once it ends the conversation takes the next one.
    assert done([event async for event in open_turn.events()]).stop_reason == "end_turn"
    assert done(await run(service, "Three", conversation_id=conversation_id)).stop_reason == (
        "end_turn"
    )


class HangingModel:
    """Reports a usage, sends one delta, then waits until its stream is closed."""

    def __init__(self) -> None:
        self.reached_the_wait = asyncio.Event()
        self.closed = False

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        try:
            yield ModelUsageSoFar(usage=usage(7))
            yield ModelTextDelta(text="Working on it.")
            self.reached_the_wait.set()
            await asyncio.Event().wait()
        finally:
            self.closed = True


@pytest.mark.req("R-10.3-4")
async def test_a_cancelled_turn_is_charged_and_releases_the_conversation() -> None:
    kit = build_turn_kit()
    model = HangingModel()
    service = kit.service(model)
    turn = await service.open_turn(BROWSER, VISITOR, chat_request())
    seen = []

    async def consume() -> None:
        async for event in turn.events():
            seen.append(event)

    task = asyncio.create_task(consume())
    await model.reached_the_wait.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert names(seen) == ["Started", "TextDelta"]
    assert model.closed
    assert kit.access_calls("may_spend", "record_spend") == ["may_spend", "record_spend"]
    assert kit.access.spent_usd_micros == 7
    state = await kit.store.load(BROWSER.workspace_id, turn.conversation_id)
    assert state.total_tokens == 7
    assert state.turns[0].finished_at is not None
    # The cut step is not stored; the history is the user message alone and still valid.
    assert len(state.entries) == 1
    again, _ = kit.scripted(say("Hello."))
    assert done(await run(again, "Hi", conversation_id=turn.conversation_id)).stop_reason == (
        "end_turn"
    )


async def test_a_stream_closed_by_its_reader_settles_the_turn() -> None:
    kit = build_turn_kit()
    model = HangingModel()
    stream = kit.service(model).chat(BROWSER, VISITOR, chat_request())
    first = await anext(stream)
    assert isinstance(first, Started)
    assert isinstance(await anext(stream), TextDelta)

    await stream.aclose()

    assert model.closed
    assert kit.access.spent_usd_micros == 7
    state = await kit.store.load(BROWSER.workspace_id, first.conversation_id)
    assert state.turns[0].finished_at is not None


async def test_shutdown_ends_the_turn_with_shutting_down_then_done_error() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(say("Never asked for."))
    kit.shutdown.set()

    events = await run(service)

    assert names(events) == ["Started", "StreamError", "Done"]
    assert events[1].model_dump()["code"] == "shutting_down"
    assert done(events).stop_reason == "error"
    assert model.requests == []


@pytest.mark.req("R-15-5")
async def test_spans_have_names_and_no_payloads() -> None:
    kit = build_turn_kit()
    secret_text = "Tell me about farm Santa Fe 4411"
    service, _ = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, call_id="c1", usage=usage(40)),
        call_tool("get_weather_history", BAD_POINT, call_id="c2", usage=usage(50)),
        say("The premium is R$ 99,999.00.", usage=usage(60)),
    )
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)
    try:
        events = await run(service, secret_text)
    finally:
        telemetry.shutdown()

    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == [
        "llm.call",
        "tool.resolve_location",
        "llm.call",
        "tool.get_weather_history",
        "llm.call",
        "agent.turn",
    ]
    turn_span = spans[-1]
    assert turn_span.parent is None
    assert all(
        span.parent is not None and span.parent.span_id == turn_span.context.span_id
        for span in spans[:-1]
    )
    assert dict(turn_span.attributes or {}) == {
        telemetry.ATTR_AGENT_CONVERSATION_ID: started(events).conversation_id,
        telemetry.ATTR_AGENT_PROMPT_VERSION: load_system_prompt().version,
        telemetry.ATTR_AGENT_STOP_REASON: "end_turn",
        telemetry.ATTR_AGENT_TOOL_CALLS: 2,
        telemetry.ATTR_AGENT_UNGROUNDED_FIGURES: 1,
    }
    first_call = dict(spans[0].attributes or {})
    latency = first_call.pop(telemetry.ATTR_LLM_LATENCY_MS)
    assert isinstance(latency, int)
    assert latency >= 0
    assert first_call == {
        telemetry.ATTR_LLM_MODEL: settings_for_tests().agent_model,
        telemetry.ATTR_LLM_INPUT_TOKENS: 40,
        telemetry.ATTR_LLM_OUTPUT_TOKENS: 0,
        telemetry.ATTR_LLM_STOP_REASON: "tool_use",
        telemetry.ATTR_LLM_COST_USD_MICROS: 40,  # the access fake: one micro-dollar a token
    }
    ok_tool, failed_tool = dict(spans[1].attributes or {}), dict(spans[3].attributes or {})
    assert ok_tool[telemetry.ATTR_TOOL_STATUS] == "ok"
    assert set(ok_tool) == {telemetry.ATTR_TOOL_STATUS, telemetry.ATTR_TOOL_DURATION_MS}
    assert failed_tool[telemetry.ATTR_TOOL_STATUS] == "error"
    assert failed_tool[telemetry.ATTR_TOOL_ERROR_CODE] == "invalid_arguments"
    # Nothing a visitor or a tool wrote: no message text, no argument, no result, no figure.
    recorded = json.dumps(
        [[span.name, dict(span.attributes or {}), [e.name for e in span.events]] for span in spans]
    )
    for payload in (secret_text, "Sorriso", "99,999", "999.0"):
        assert payload not in recorded
    assert isinstance(finished_tools(events)[0], ToolFinished)
