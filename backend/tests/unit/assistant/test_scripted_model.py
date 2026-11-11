"""The scripted model client: steps, policies, scripted failures and the built-in scenario."""

from collections.abc import Mapping

import pytest

from tests.fakes.builders import backtest_result, priced_cover
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelClient,
    ModelCompleted,
    ModelEvent,
    ModelMessage,
    ModelRequest,
    ModelTextDelta,
    ModelToolCall,
    ModelUnavailable,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)
from veranico.modules.assistant.domain.grounding import check_grounding
from veranico.modules.assistant.infrastructure.scripted_model import (
    FailAfter,
    Played,
    ScriptedModelClient,
    ScriptExhaustedError,
    call_tool,
    say,
    tool_results,
)

MODEL = "test-model"
SUBMISSION_TOOL = ToolSpec(
    name="request_submission",
    description="Request submission to a carrier.",
    input_schema={
        "type": "object",
        "properties": {
            "quote_id": {"type": "string"},
            "carrier_id": {"type": "string", "enum": ["carrier-2", "carrier-1"]},
        },
    },
)


def request(
    *messages: ModelMessage, tools: tuple[ToolSpec, ...] = (), tool_use: str = "auto"
) -> ModelRequest:
    assert tool_use in ("auto", "none")
    return ModelRequest(
        model=MODEL,
        system="system",
        messages=messages,
        tools=tools,
        max_output_tokens=1_000,
        tool_use="none" if tool_use == "none" else "auto",
    )


def user(text: str) -> ModelMessage:
    return ModelMessage(role="user", blocks=(TextBlock(text=text),))


async def play(client: ModelClient, model_request: ModelRequest) -> list[ModelEvent]:
    return [event async for event in client.stream(model_request)]


def text_of(events: list[ModelEvent]) -> str:
    return "".join(event.text for event in events if isinstance(event, ModelTextDelta))


async def test_plays_steps_in_order() -> None:
    client = ScriptedModelClient(
        [call_tool("resolve_location", {"query": "Varginha"}), say("Found it. It is in Minas.")]
    )

    first = await play(client, request(user("where?")))
    second = await play(client, request(user("where?")))

    assert first == [
        ModelToolCall(call_id="call-1", name="resolve_location", arguments={"query": "Varginha"}),
        ModelCompleted(
            stop="tool_use", usage=ModelUsage(model="scripted", input_tokens=0, output_tokens=0)
        ),
    ]
    assert text_of(second) == "Found it. It is in Minas."
    assert [type(event) for event in second] == [ModelTextDelta, ModelTextDelta, ModelCompleted]
    last = second[-1]
    assert isinstance(last, ModelCompleted)
    assert last.stop == "end_turn"


async def test_function_step_sees_earlier_tool_results() -> None:
    def cite(model_request: ModelRequest) -> Played:
        [(name, block)] = tool_results(model_request)
        return say(f"{name} returned quote {block.content['quote_id']}")

    client = ScriptedModelClient([cite])
    history = (
        user("price it"),
        ModelMessage(
            role="assistant",
            blocks=(ToolCallBlock(call_id="c1", name="price_cover", arguments={}),),
        ),
        ModelMessage(
            role="user",
            blocks=(ToolResultBlock(call_id="c1", content={"quote_id": "Q-7K3M9P"}),),
        ),
    )

    events = await play(client, request(*history))

    assert text_of(events) == "price_cover returned quote Q-7K3M9P"


async def test_raises_after_n_events_when_scripted() -> None:
    usage = ModelUsage(model=MODEL, input_tokens=120, output_tokens=7)
    client = ScriptedModelClient(
        [
            FailAfter(
                events=(ModelTextDelta(text="I am "), ModelTextDelta(text="loading")), usage=usage
            )
        ]
    )
    seen: list[ModelEvent] = []

    async def drain() -> None:
        async for event in client.stream(request(user("go"))):
            seen.append(event)  # one by one, to keep what arrived before the failure

    with pytest.raises(ModelUnavailable) as raised:
        await drain()

    assert seen == [ModelTextDelta(text="I am "), ModelTextDelta(text="loading")]
    assert raised.value.usage == usage


async def test_failure_before_any_event_carries_no_usage() -> None:
    client = ScriptedModelClient([FailAfter()])

    with pytest.raises(ModelUnavailable) as raised:
        await play(client, request(user("go")))

    assert raised.value.usage is None


async def test_exhausted_script_fails_loudly() -> None:
    client = ScriptedModelClient([say("Only one answer.")])
    await play(client, request(user("one")))

    with pytest.raises(ScriptExhaustedError, match="1 steps and call 2"):
        await play(client, request(user("two")))


async def test_records_requests() -> None:
    client = ScriptedModelClient([say("a"), say("b")])
    first, second = request(user("one")), request(user("two"))

    await play(client, first)
    await play(client, second)

    assert client.requests == [first, second]


async def test_a_policy_answers_every_call() -> None:
    client = ScriptedModelClient(lambda model_request: say(f"{len(model_request.messages)}"))

    assert text_of(await play(client, request(user("a")))) == "1"
    assert text_of(await play(client, request(user("a"), user("b")))) == "2"
    assert len(client.requests) == 2


# The built-in scenario, driven the way the turn loop drives a model.

LOCATION = {
    "label": "Três Pontas",
    "lat": -21.37,
    "lon": -45.51,
    "h3_cell": "86a8a0c57ffffff",
    "admin_region": "Minas Gerais",
    "country_code": "BR",
}
DATASET = {
    "dataset_id": "cube:sul-de-minas:13:9",
    "kind": "cube",
    "region_id": "sul-de-minas",
    "grid_point": {"lat": -21.4, "lon": -45.5},
    "first_year": 1950,
    "last_year": 2025,
    "days": 27_759,
    "missing_days": 0,
    "source": "synthetic",
}
CANNED: dict[str, Mapping[str, object]] = {
    "resolve_location": LOCATION,
    "get_weather_history": DATASET,
    "backtest_index": backtest_result(trend_significant=True).model_dump(mode="json"),
    "price_cover": {
        "quote_id": "Q-7K3M9P",
        "priced": priced_cover(trend_significant=True).model_dump(mode="json"),
    },
    "draft_term_sheet": {"documents": [{"locale": "en"}, {"locale": "pt-BR"}]},
    "request_submission": {"submission_id": "S-4T8W2X", "carrier_id": "carrier-2"},
}
USER_TURNS = [
    "Coffee farm near Três Pontas, MG. Pay when Sep-Oct rainfall is below 150 mm, in full at "
    "75 mm. Limit R$ 300,000.",
    "Yes, price it.",
    "Draft the term sheet.",
    "Request submission.",
]


async def run_turn(
    client: ScriptedModelClient,
    messages: list[ModelMessage],
    text: str,
    canned: Mapping[str, Mapping[str, object]] = CANNED,
) -> tuple[str, list[ModelToolCall]]:
    """One user turn: call the model until it answers without asking for a tool."""
    messages.append(user(text))
    calls: list[ModelToolCall] = []
    for _ in range(10):
        events = await play(client, request(*messages, tools=(SUBMISSION_TOOL,)))
        asked = [event for event in events if isinstance(event, ModelToolCall)]
        if not asked:
            return text_of(events), calls
        calls.extend(asked)
        messages.append(
            ModelMessage(
                role="assistant",
                blocks=tuple(
                    ToolCallBlock(call_id=c.call_id, name=c.name, arguments=c.arguments)
                    for c in asked
                ),
            )
        )
        messages.append(
            ModelMessage(
                role="user",
                blocks=tuple(
                    ToolResultBlock(
                        call_id=c.call_id,
                        content=canned[c.name],
                        is_error="error_code" in canned[c.name],
                    )
                    for c in asked
                ),
            )
        )
    raise AssertionError("the scenario did not answer within ten model calls")


async def test_happy_path_walks_the_flow_over_four_user_turns() -> None:
    client = ScriptedModelClient.happy_path()
    messages: list[ModelMessage] = []

    turns = [await run_turn(client, messages, text) for text in USER_TURNS]

    assert [[call.name for call in calls] for _, calls in turns] == [
        ["resolve_location", "get_weather_history", "backtest_index"],
        ["price_cover"],
        ["draft_term_sheet"],
        ["request_submission"],
    ]
    calls = [call for _, turn_calls in turns for call in turn_calls]
    assert calls[0].arguments == {"query": "Três Pontas"}
    assert calls[1].arguments == {"lat": -21.37, "lon": -45.51}
    assert calls[2].arguments == {
        "dataset_id": "cube:sul-de-minas:13:9",
        "index_type": "rainfall_below",
        "window_start": "09-01",
        "window_end": "10-31",
        "trigger": 150.0,
        "exit": 75.0,
        "limit_cents": 30_000_000,
    }
    assert calls[3].arguments == {
        "lat": -21.37,
        "lon": -45.51,
        "label": "Três Pontas",
        "admin_region": "Minas Gerais",
        "index_type": "rainfall_below",
        "window_start": "09-01",
        "window_end": "10-31",
        "trigger": 150.0,
        "exit": 75.0,
        "limit_cents": 30_000_000,
        "n": 100_000,
        "seed": 42,
    }
    assert "dataset_id" not in calls[3].arguments
    assert calls[4].arguments == {"quote_id": "Q-7K3M9P"}
    # The carrier is the first one the tool definition allows.
    assert calls[5].arguments == {"quote_id": "Q-7K3M9P", "carrier_id": "carrier-2"}
    assert len({call.call_id for call in calls}) == len(calls)
    assert "Q-7K3M9P" in turns[1][0]
    assert "S-4T8W2X" in turns[3][0]
    assert "cannot approve" in turns[3][0]


@pytest.mark.req("R-9.5-4")
async def test_happy_path_scenario_cites_only_figures_from_results() -> None:
    client = ScriptedModelClient.happy_path()
    messages: list[ModelMessage] = []

    answers = [(await run_turn(client, messages, text))[0] for text in USER_TURNS]

    cited = 0
    for answer in answers:
        # No user text among the sources: every figure must come from a tool result.
        report = check_grounding(answer, list(CANNED.values()), [], "en")
        assert report.ungrounded == (), answer
        cited += len(report.figures)
    assert cited >= 7  # frequency, burn cost, largest payout; three payouts, premium, rate


async def test_happy_path_says_when_the_weather_data_is_synthetic() -> None:
    client = ScriptedModelClient.happy_path()
    messages: list[ModelMessage] = []

    backtest_answer, _ = await run_turn(client, messages, USER_TURNS[0])
    price_answer, _ = await run_turn(client, messages, USER_TURNS[1])

    assert "synthetic, not real weather history" in backtest_answer
    assert "synthetic, not real weather history" in price_answer
    assert "significant trend" in backtest_answer


async def test_happy_path_names_a_real_source_instead_of_calling_it_synthetic() -> None:
    client = ScriptedModelClient.happy_path()
    canned = {**CANNED, "get_weather_history": {**DATASET, "source": "era5/open-meteo"}}

    answer, _ = await run_turn(client, [], USER_TURNS[0], canned)

    assert "era5/open-meteo" in answer
    assert "synthetic" not in answer


async def test_happy_path_takes_the_first_candidate_of_an_ambiguous_place() -> None:
    client = ScriptedModelClient.happy_path()
    other = {**LOCATION, "label": "Três Pontas (other)", "lat": -10.0, "lon": -50.0}
    canned = {**CANNED, "resolve_location": {"candidates": [LOCATION, other]}}

    _, calls = await run_turn(client, [], USER_TURNS[0], canned)

    assert calls[1].arguments == {"lat": -21.37, "lon": -45.51}


async def test_happy_path_stops_and_names_the_code_when_a_tool_fails() -> None:
    client = ScriptedModelClient.happy_path()
    error = {"error_code": "weather_source_unavailable", "message": "try later", "retryable": True}
    canned = {**CANNED, "get_weather_history": error}

    answer, calls = await run_turn(client, [], USER_TURNS[0], canned)

    assert [call.name for call in calls] == ["resolve_location", "get_weather_history"]
    assert "weather_source_unavailable" in answer


async def test_happy_path_answers_in_text_when_tools_are_not_allowed() -> None:
    client = ScriptedModelClient.happy_path()

    events = await play(client, request(user(USER_TURNS[0]), tool_use="none"))

    assert not [event for event in events if isinstance(event, ModelToolCall)]
    assert text_of(events)


async def test_happy_path_reports_zero_usage_for_the_requested_model() -> None:
    client = ScriptedModelClient.happy_path()

    events = await play(client, request(user(USER_TURNS[0])))

    assert events[-1] == ModelCompleted(
        stop="tool_use", usage=ModelUsage(model=MODEL, input_tokens=0, output_tokens=0)
    )


async def test_happy_path_serves_two_conversations_from_one_client() -> None:
    # `make dev` builds one client for the whole process: it must keep no conversation state.
    client = ScriptedModelClient.happy_path()
    first: list[ModelMessage] = []
    second: list[ModelMessage] = []

    _, first_calls = await run_turn(client, first, USER_TURNS[0])
    _, second_calls = await run_turn(client, second, USER_TURNS[0])
    _, priced = await run_turn(client, first, USER_TURNS[1])

    assert [call.name for call in first_calls] == [call.name for call in second_calls]
    assert [call.name for call in priced] == ["price_cover"]
