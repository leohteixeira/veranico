"""Unexpected failures inside a turn (SPEC 9.1).

A tool that raises something other than a `DomainError` is a tool error the model reads, and
any other unexpected failure of the turn ends the stream with `error` and then `done`. Either
way the conversation stays consistent: it loads, its claim is released and the next message
is answered.
"""

from collections.abc import Sequence

import pytest

from tests.unit.assistant.store_contract import TTL
from tests.unit.assistant.tools.kit import BROWSER
from tests.unit.assistant.turn_kit import (
    SORRISO_QUERY,
    build_turn_kit,
    done,
    finished_tools,
    names,
    run,
    started,
)
from veranico.modules.assistant.application.ports import ModelRequest
from veranico.modules.assistant.contracts import StreamError
from veranico.modules.assistant.domain.conversation import Entry, is_valid_history
from veranico.modules.assistant.infrastructure.memory_conversations import MemoryConversationStore
from veranico.modules.assistant.infrastructure.scripted_model import (
    Played,
    call_tool,
    say,
    tool_results,
)
from veranico.shared.kernel.ids import ConversationId

pytestmark = pytest.mark.req("R-9.1-1")

# A point the climate fake has no series for: it raises `LookupError`, which is no
# `DomainError`; it stands for any defect or infrastructure failure under a tool.
UNREGISTERED_POINT = {"lat": -20.0, "lon": -50.0}


class FailingAppendStore(MemoryConversationStore):
    """The memory store, failing every `append` after the first `allowed` ones."""

    allowed = 1  # the user message of the turn

    async def append(self, conversation_id: ConversationId, entries: Sequence[Entry]) -> None:
        if self.allowed <= 0:
            raise OSError("the store is unreachable at /var/run/store.sock")
        self.allowed -= 1
        await super().append(conversation_id, entries)


def _stream_error(events: Sequence[object]) -> StreamError:
    [error] = [event for event in events if isinstance(event, StreamError)]
    return error


@pytest.mark.req("R-9.1-3")
async def test_a_tool_that_raises_is_a_tool_error_the_model_reads_and_the_turn_goes_on() -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("get_weather_history", UNREGISTERED_POINT, call_id="c1"),
        say("Loading the history failed; nothing else was done."),
    )

    events = await run(service)

    (finished,) = finished_tools(events)
    assert finished.status == "error"
    assert finished.error is not None
    assert finished.error.error_code == "internal_error"
    assert finished.error.retryable is False
    assert done(events).stop_reason == "end_turn"
    assert "StreamError" not in names(events)
    # The model read the structured error as the tool result.
    [(tool, block)] = tool_results(model.requests[1])
    assert tool == "get_weather_history"
    assert block.is_error
    # After a reload the conversation shows the failed tool and the answer.
    view = await service.conversation(BROWSER, started(events).conversation_id)
    assert view.messages[-1].tools == [finished]


async def test_a_store_failure_mid_turn_ends_with_error_then_done_and_stays_usable() -> None:
    kit = build_turn_kit()
    kit.store = FailingAppendStore(kit.clock, ttl=TTL)
    service, _ = kit.scripted(call_tool("resolve_location", SORRISO_QUERY, call_id="c1"))

    events = await run(service)

    assert names(events)[-2:] == ["StreamError", "Done"]
    error = _stream_error(events)
    assert error == StreamError(code="internal_error", completed=["resolve_location"])
    assert done(events).stop_reason == "error"
    # The step that could not be written is not stored; the turn is finished and released.
    conversation_id = started(events).conversation_id
    state = await kit.store.load(BROWSER.workspace_id, conversation_id)
    assert state.turns[-1].finished_at is not None
    assert is_valid_history(state.entries)
    kit.store.allowed = 10
    again, _ = kit.scripted(say("Hello again."))
    assert done(await run(again, "Hi", conversation_id=conversation_id)).stop_reason == "end_turn"


async def test_a_model_client_defect_ends_with_error_then_done() -> None:
    def broken(request: ModelRequest) -> Played:
        raise RuntimeError("a defect in the client, with /internal/path")

    kit = build_turn_kit()
    service, _ = kit.scripted(broken)

    events = await run(service)

    assert names(events) == ["Started", "StreamError", "Done"]
    assert _stream_error(events) == StreamError(code="internal_error", completed=[])
    assert done(events).stop_reason == "error"
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    assert state.turns[-1].finished_at is not None
