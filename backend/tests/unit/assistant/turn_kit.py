"""A chat service over the fakes, the memory store and a scripted model, for the turn tests.

`run` plays one turn to its end and checks the order rules of the stream on every turn it
plays, so each test of the loop also proves them.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from tests.fakes.access import FakeAccessFacade
from tests.fakes.settings import settings_for_tests
from tests.unit.assistant.store_contract import NOW, TTL
from tests.unit.assistant.tools.kit import BROWSER, Kit, build_kit
from veranico.modules.access.contracts import ModelUsage, VisitorRef
from veranico.modules.assistant.application.chat_service import ChatService
from veranico.modules.assistant.application.ports import ModelClient
from veranico.modules.assistant.application.prompt import load_system_prompt
from veranico.modules.assistant.application.turn import TurnDeps
from veranico.modules.assistant.contracts import (
    AgentEvent,
    ChatRequest,
    Done,
    GroundingFlagged,
    Started,
    StreamError,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from veranico.modules.assistant.infrastructure.memory_conversations import MemoryConversationStore
from veranico.modules.assistant.infrastructure.scripted_model import ScriptedModelClient, Step
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import ConversationId, Locale
from veranico.shared.kernel.principal import Principal

VISITOR = VisitorRef(ip_hash="visitor-hash-1", boosted=False)
MESSAGE = "A soy farm near Sorriso"
SORRISO_QUERY = {"query": "Sorriso"}
# Rejected by the tool's input model: the latitude is out of range.
BAD_POINT = {"lat": 999.0, "lon": 0.0}


def usage(tokens: int) -> ModelUsage:
    """A usage of `tokens` tokens in total, which the access fake charges one micro-dollar each."""
    return ModelUsage(model="scripted", input_tokens=tokens, output_tokens=0)


@dataclass
class TurnKit:
    tools: Kit
    access: FakeAccessFacade
    store: MemoryConversationStore
    clock: FixedClock
    shutdown: asyncio.Event
    settings_overrides: dict[str, Any]

    def service(self, model: ModelClient) -> ChatService:
        return ChatService(
            TurnDeps(
                settings=settings_for_tests(**self.settings_overrides),
                access=self.access,
                store=self.store,
                model=model,
                registry=self.tools.registry,
                prompt=load_system_prompt(),
                shutdown=self.shutdown,
            )
        )

    def scripted(self, *steps: Step) -> tuple[ChatService, ScriptedModelClient]:
        model = ScriptedModelClient(steps)
        return self.service(model), model

    def access_calls(self, *names: str) -> list[str]:
        """The names of the calls the access facade received, in order, limited to `names`."""
        return [name for name, _ in self.access.calls if name in names]


def build_turn_kit(**settings_overrides: Any) -> TurnKit:
    clock = FixedClock(NOW)
    return TurnKit(
        tools=build_kit(),
        access=FakeAccessFacade(clock=clock),
        store=MemoryConversationStore(clock, ttl=TTL),
        clock=clock,
        shutdown=asyncio.Event(),
        settings_overrides=settings_overrides,
    )


def chat_request(
    message: str = MESSAGE,
    conversation_id: ConversationId | None = None,
    locale: Locale = "en",
) -> ChatRequest:
    return ChatRequest(conversation_id=conversation_id, message=message, locale=locale)


async def run(
    service: ChatService,
    message: str = MESSAGE,
    *,
    conversation_id: ConversationId | None = None,
    locale: Locale = "en",
    principal: Principal = BROWSER,
) -> list[AgentEvent]:
    """Play one turn to its end and return its events."""
    turn = await service.open_turn(
        principal, VISITOR, chat_request(message, conversation_id, locale)
    )
    events = [event async for event in turn.events()]
    assert_stream_order(events)
    return events


def assert_stream_order(events: Sequence[AgentEvent]) -> None:
    """The order rules of contracts section 8, for a stream that reached its end."""
    kinds = [type(event) for event in events]
    assert kinds[0] is Started
    assert kinds[-1] is Done
    assert kinds.count(Started) == 1
    assert kinds.count(Done) == 1
    for index, kind in enumerate(kinds):
        if kind is StreamError:
            assert kinds[index + 1] is Done
    open_calls: list[str] = []
    for event in events:
        if isinstance(event, ToolStarted):
            assert not open_calls, "tools run one after another"
            open_calls.append(event.call_id)
        elif isinstance(event, ToolFinished):
            assert open_calls == [event.call_id]
            open_calls.clear()
    assert not open_calls
    if GroundingFlagged in kinds and TextDelta in kinds:
        last_delta = max(index for index, kind in enumerate(kinds) if kind is TextDelta)
        assert kinds.index(GroundingFlagged) > last_delta


def names(events: Sequence[AgentEvent]) -> list[str]:
    return [type(event).__name__ for event in events]


def text_of(events: Sequence[AgentEvent]) -> str:
    return "".join(event.text for event in events if isinstance(event, TextDelta))


def done(events: Sequence[AgentEvent]) -> Done:
    last = events[-1]
    assert isinstance(last, Done)
    return last


def started(events: Sequence[AgentEvent]) -> Started:
    first = events[0]
    assert isinstance(first, Started)
    return first


def finished_tools(events: Sequence[AgentEvent]) -> list[ToolFinished]:
    return [event for event in events if isinstance(event, ToolFinished)]
