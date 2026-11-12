"""The grounding check inside a turn (SPEC 9.5): it flags, stores and never holds text back."""

from collections.abc import Sequence

import pytest

from tests.unit.assistant.tools.kit import BROWSER, LIMIT_CENTS
from tests.unit.assistant.turn_kit import (
    build_turn_kit,
    done,
    finished_tools,
    names,
    run,
    started,
    text_of,
)
from veranico.modules.assistant.contracts import GroundingFlagged
from veranico.modules.assistant.infrastructure.scripted_model import call_tool, say

INVENTED = "The premium is R$ 99,999.00."


def flagged(events: Sequence[object]) -> list[GroundingFlagged]:
    return [event for event in events if isinstance(event, GroundingFlagged)]


@pytest.mark.req("R-9.5-2")
async def test_ungrounded_figure_emits_grounding_flagged_and_stores_marker() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say(INVENTED))

    events = await run(service)

    assert flagged(events) == [
        GroundingFlagged(message_id=started(events).message_id, values=["R$ 99,999.00"])
    ]
    conversation_id = started(events).conversation_id
    state = await kit.store.load(BROWSER.workspace_id, conversation_id)
    assert state.turns[0].flagged == ("R$ 99,999.00",)
    view = await service.conversation(BROWSER, conversation_id)
    assert view.messages[-1].message_id == started(events).message_id
    assert view.messages[-1].flagged == ["R$ 99,999.00"]


@pytest.mark.req("R-9.5-3")
async def test_grounding_runs_after_the_last_delta_and_never_withholds_text() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(say(f"{INVENTED} It is illustrative."))

    events = await run(service)

    assert text_of(events) == f"{INVENTED} It is illustrative."
    assert names(events)[-2:] == ["GroundingFlagged", "Done"]
    assert done(events).stop_reason == "end_turn"


@pytest.mark.req("R-9.5-2")
async def test_a_figure_from_a_tool_result_of_the_conversation_is_not_flagged() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(
        call_tool("price_cover", kit.tools.price_arguments(), call_id="c1"),
        say("The limit is R$ 300,000.00."),
        say("As said, the limit is R$ 300,000.00, not R$ 123,456.00."),
    )
    assert LIMIT_CENTS == 30_000_000
    first = await run(service, "Price it")
    assert finished_tools(first)[0].status == "ok"
    assert flagged(first) == []

    # A later turn is checked against the results of the whole conversation.
    second = await run(service, "Repeat", conversation_id=started(first).conversation_id)

    assert [event.values for event in flagged(second)] == [["R$ 123,456.00"]]


@pytest.mark.req("R-9.5-2")
async def test_text_of_every_step_of_the_turn_is_checked() -> None:
    kit = build_turn_kit()
    service, _ = kit.scripted(
        call_tool("resolve_location", {"query": "Sorriso"}, text="It may cost R$ 77,777.00."),
        say("Found the place."),
    )

    events = await run(service)

    assert [event.values for event in flagged(events)] == [["R$ 77,777.00"]]
