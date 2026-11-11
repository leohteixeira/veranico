"""What stops a turn: the allowance, the spend ceiling, the budgets, the tool limit, failures."""

from collections.abc import Sequence

import pytest

from tests.unit.assistant.tools.kit import BROWSER, SORRISO
from tests.unit.assistant.turn_kit import (
    BAD_POINT,
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
    ModelCompleted,
    ModelRequest,
    ModelToolCall,
)
from veranico.modules.assistant.application.prompt import WRAP_UP_NOTE
from veranico.modules.assistant.application.turn import TOOL_NOT_EXECUTED
from veranico.modules.assistant.contracts import ApprovalRequired, StreamError, ToolError
from veranico.modules.assistant.domain.conversation import is_valid_history
from veranico.modules.assistant.infrastructure.scripted_model import (
    FailAfter,
    Played,
    call_tool,
    no_usage,
    say,
    tool_results,
)
from veranico.shared.kernel.errors import (
    AllowanceExhaustedError,
    MessageTooLongError,
    SpendCeilingReachedError,
)

SPEND_CALLS = ("admit_message", "may_spend", "record_spend")


def stream_error(events: Sequence[object]) -> StreamError:
    (error,) = (event for event in events if isinstance(event, StreamError))
    return error


def last_text(request: ModelRequest) -> str:
    block = request.messages[-1].blocks[-1]
    return getattr(block, "text", "")


@pytest.mark.req("R-10.3-4")
async def test_admit_message_runs_once_per_turn_and_may_spend_before_every_model_call() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, call_id="c1"),
        call_tool("resolve_location", SORRISO_QUERY, call_id="c2"),
        say("Done."),
    )

    await run(service)

    assert len(model.requests) == 3
    assert kit.access_calls(*SPEND_CALLS) == [
        "admit_message",
        *["may_spend", "record_spend"] * 3,
    ]
    assert kit.access.calls[0] == ("admit_message", (VISITOR, True))


@pytest.mark.req("R-10.3-4")
async def test_a_message_in_an_existing_conversation_is_admitted_as_not_new() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say("Hello."), say("Hello again."))
    conversation_id = started(await run(service)).conversation_id
    kit.access.calls.clear()

    await run(service, "More", conversation_id=conversation_id)

    assert kit.access.calls[0] == ("admit_message", (VISITOR, False))


@pytest.mark.req("R-10.3-4", "R-9.1-2")
async def test_record_spend_follows_every_model_call_including_wrap_up() -> None:
    kit = build_turn_kit(assistant={"tool_call_limit": 1})
    service, _ = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, usage=usage(11)),
        say("One place resolved; nothing else was done.", usage=usage(13)),
    )

    events = await run(service)

    assert done(events).stop_reason == "tool_limit"
    recorded = [arguments[0] for name, arguments in kit.access.calls if name == "record_spend"]
    assert recorded == [usage(11), usage(13)]
    assert kit.access.spent_usd_micros == 24
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    assert state.total_tokens == 24


@pytest.mark.req("R-10.3-4")
async def test_a_failed_model_call_is_charged_what_it_used() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(FailAfter(usage=usage(9)))

    events = await run(service)

    assert kit.access_calls(*SPEND_CALLS) == ["admit_message", "may_spend", "record_spend"]
    assert kit.access.spent_usd_micros == 9
    assert stream_error(events) == StreamError(code="model_unavailable", completed=[])
    assert done(events).stop_reason == "error"


@pytest.mark.req("R-10.3-6")
async def test_denied_ceiling_before_stream_raises_and_consumes_no_message() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(say("Never asked for."))
    before = await kit.access.allowance(VISITOR)
    kit.access.ceiling_usd_micros = 0

    for reason in ("day_ceiling", "month_ceiling"):
        kit.access.ceiling_reason = reason
        with pytest.raises(SpendCeilingReachedError):
            await service.open_turn(BROWSER, VISITOR, chat_request())

    assert await kit.access.allowance(VISITOR) == before
    assert kit.access_calls("may_spend", "record_spend") == []
    assert model.requests == []


@pytest.mark.req("R-10.3-6")
async def test_denied_allowance_raises_allowance_exhausted() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(*[say("Hello.")] * 15)
    conversation_id = started(await run(service)).conversation_id
    for _ in range(14):
        await run(service, "More", conversation_id=conversation_id)

    with pytest.raises(AllowanceExhaustedError):
        await service.open_turn(BROWSER, VISITOR, chat_request("More", conversation_id))

    assert len(model.requests) == 15
    # The refused message opened no turn.
    state = await kit.store.load(BROWSER.workspace_id, conversation_id)
    assert len(state.turns) == 15


@pytest.mark.req("R-10.3-5")
async def test_message_too_long_is_rejected_before_admission() -> None:
    kit = build_turn_kit(access={"max_message_chars": 20})
    service, model = kit.scripted(say("Hello."))

    with pytest.raises(MessageTooLongError):
        await service.open_turn(BROWSER, VISITOR, chat_request("x" * 21))

    assert kit.access.calls == []
    assert model.requests == []
    assert done(await run(service, "x" * 20)).stop_reason == "end_turn"


@pytest.mark.req("R-10.3-4")
async def test_ceiling_mid_turn_ends_with_error_then_budget() -> None:
    kit = build_turn_kit()
    kit.access.ceiling_usd_micros = 30
    service, model = kit.scripted(
        call_tool("resolve_location", SORRISO_QUERY, usage=usage(30)),
        say("Never asked for."),
    )

    events = await run(service)

    assert names(events) == ["Started", "ToolStarted", "ToolFinished", "StreamError", "Done"]
    assert stream_error(events) == StreamError(
        code="spend_ceiling_reached", completed=["resolve_location"]
    )
    assert done(events).stop_reason == "budget"
    assert len(model.requests) == 1
    # The finished step is stored, so the conversation can go on later.
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    assert is_valid_history(state.entries)
    assert len(state.entries) == 3


@pytest.mark.req("R-10.3-5")
async def test_conversation_budget_ends_with_done_budget_and_no_error_event() -> None:
    kit = build_turn_kit(access={"conversation_token_budget": 100})
    service, model = kit.scripted(
        say("First answer.", usage=usage(60)),
        call_tool("resolve_location", SORRISO_QUERY, usage=usage(40)),
        say("Never asked for."),
    )
    conversation_id = started(await run(service)).conversation_id

    second = await run(service, "More", conversation_id=conversation_id)

    assert names(second) == ["Started", "ToolStarted", "ToolFinished", "Done"]
    assert done(second).stop_reason == "budget"
    assert len(model.requests) == 2
    # The budget is the conversation's: the next turn makes no model call at all.
    third = await run(service, "Again", conversation_id=conversation_id)
    assert names(third) == ["Started", "Done"]
    assert done(third).stop_reason == "budget"
    assert len(model.requests) == 2


@pytest.mark.req("R-9.1-2")
async def test_tenth_tool_call_triggers_wrap_up_and_tool_limit() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        *[call_tool("resolve_location", SORRISO_QUERY, call_id=f"c{n}") for n in range(10)],
        say("Ten lookups are done; pricing is still pending."),
    )

    events = await run(service)

    assert [tool.status for tool in finished_tools(events)] == ["ok"] * 10
    assert len(model.requests) == 11
    assert [request.tool_use for request in model.requests] == ["auto"] * 10 + ["none"]
    assert last_text(model.requests[-1]) == WRAP_UP_NOTE
    assert text_of(events) == "Ten lookups are done; pricing is still pending."
    assert done(events).stop_reason == "tool_limit"


def three_calls(_: ModelRequest) -> Played:
    return (
        *[
            ModelToolCall(call_id=f"c{n}", name="resolve_location", arguments=SORRISO_QUERY)
            for n in range(3)
        ],
        ModelCompleted(stop="tool_use", usage=no_usage()),
    )


@pytest.mark.req("R-9.1-2")
async def test_calls_beyond_the_limit_are_not_executed() -> None:
    kit = build_turn_kit(assistant={"tool_call_limit": 2})
    service, model = kit.scripted(three_calls, say("Two lookups are done."))

    events = await run(service)

    assert [tool.status for tool in finished_tools(events)] == ["ok", "ok", "error"]
    refused = finished_tools(events)[2]
    assert refused.error is not None
    assert refused.error.error_code == TOOL_NOT_EXECUTED
    assert refused.error.retryable is False
    assert [name for name, _ in kit.tools.climate.calls] == ["resolve_location"] * 2
    # The model reads the refusal as the result of its third call, then wraps up.
    results = tool_results(model.requests[1])
    assert [block.is_error for _, block in results] == [False, False, True]
    assert model.requests[1].tool_use == "none"
    assert done(events).stop_reason == "tool_limit"
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    assert is_valid_history(state.entries)


@pytest.mark.req("R-9.1-3")
async def test_tool_error_is_returned_to_the_model_as_structured_payload() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("get_weather_history", BAD_POINT), say("That point is not valid.")
    )

    events = await run(service)

    (finished,) = finished_tools(events)
    assert finished.status == "error"
    assert finished.result is None
    assert finished.error is not None
    assert finished.error.error_code == "invalid_arguments"
    assert finished.summary.code == "tool.error"
    ((name, block),) = tool_results(model.requests[1])
    assert name == "get_weather_history"
    assert block.is_error
    assert ToolError.model_validate(block.content) == finished.error
    assert set(block.content) == {"error_code", "message", "retryable"}
    assert done(events).stop_reason == "end_turn"


@pytest.mark.req("R-9.1-4")
async def test_one_retry_after_a_failure_is_allowed() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("get_weather_history", BAD_POINT, call_id="c1"),
        call_tool(
            "get_weather_history",
            {"lat": SORRISO.lat, "lon": SORRISO.lon},
            call_id="c2",
        ),
        call_tool("get_weather_history", BAD_POINT, call_id="c3"),
        say("The history is loaded."),
    )

    events = await run(service)

    # A success in between resets the count: the third call is a first failure again.
    assert [tool.status for tool in finished_tools(events)] == ["error", "ok", "error"]
    assert [request.tool_use for request in model.requests] == ["auto"] * 4
    assert done(events).stop_reason == "end_turn"


@pytest.mark.req("R-9.1-4")
async def test_second_consecutive_failure_of_the_same_tool_triggers_wrap_up() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("get_weather_history", BAD_POINT, call_id="c1"),
        call_tool("get_weather_history", BAD_POINT, call_id="c2"),
        say("The weather history could not be loaded; nothing was priced."),
    )

    events = await run(service)

    assert [tool.status for tool in finished_tools(events)] == ["error", "error"]
    assert [request.tool_use for request in model.requests] == ["auto", "auto", "none"]
    assert last_text(model.requests[-1]) == WRAP_UP_NOTE
    assert text_of(events) == "The weather history could not be loaded; nothing was priced."
    assert done(events).stop_reason == "end_turn"


@pytest.mark.req("R-9.1-4")
async def test_failures_of_two_different_tools_do_not_end_the_tool_use() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("get_weather_history", BAD_POINT, call_id="c1"),
        call_tool("resolve_location", {}, call_id="c2"),
        say("Both failed once."),
    )

    await run(service)

    assert [request.tool_use for request in model.requests] == ["auto"] * 3


def submit_the_priced_quote(request: ModelRequest) -> Played:
    _, priced = tool_results(request)[-1]
    return call_tool(
        "request_submission",
        {"quote_id": priced.content["quote_id"], "carrier_id": "carrier-1"},
        call_id="c2",
    )


async def test_request_submission_emits_approval_required() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(
        call_tool("price_cover", kit.tools.price_arguments(), call_id="c1"),
        submit_the_priced_quote,
        say("The submission waits for your approval."),
    )

    events = await run(service)

    priced, submitted = finished_tools(events)
    assert (priced.status, submitted.status) == ("ok", "ok")
    assert priced.result is not None
    assert submitted.result is not None
    index = events.index(submitted)
    assert events[index + 1] == ApprovalRequired(
        approval_id=submitted.result["submission_id"], quote_id=priced.result["quote_id"]
    )
    assert names(events).count("ApprovalRequired") == 1
    assert len(await kit.tools.quoting.list_approvals(BROWSER, None)) == 1
