"""In-memory fake of `AssistantFacade`: scripted event streams, no model, no I/O.

`script(events)` sets the events between `Started` and `Done` of the next streams. Every
stream starts with `Started` and ends with `Done`; a replay also carries the recorded
request as `UserMessage`, which a chat stream never does. `conversation` returns what was
streamed. `calls` lists every call received, in order.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from tests.fakes.access import Call
from veranico.modules.access.contracts import VisitorRef
from veranico.modules.assistant.contracts import (
    AgentEvent,
    ChatRequest,
    ConversationView,
    Done,
    GroundingFlagged,
    MessageView,
    Started,
    TextDelta,
    ToolFinished,
    UserMessage,
)
from veranico.shared.kernel.clock import Clock, FixedClock
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import ConversationId, Locale, WorkspaceId
from veranico.shared.kernel.principal import Principal

PROMPT_VERSION = "fake-1"
REPLAY_REQUEST = "Price a drought cover near Sorriso."
DEFAULT_SCRIPT: tuple[AgentEvent, ...] = (TextDelta(text="Hello from the fake assistant."),)


class FakeAssistantFacade:
    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or FixedClock(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
        self._script: list[AgentEvent] = list(DEFAULT_SCRIPT)
        self._owners: dict[ConversationId, WorkspaceId] = {}
        self._messages: dict[ConversationId, list[MessageView]] = {}
        self._count = 0
        self.calls: list[Call] = []

    def script(self, events: Sequence[AgentEvent]) -> None:
        """Set the events between `Started` and `Done`. Do not include either of them."""
        if any(isinstance(event, Started | Done | UserMessage) for event in events):
            raise ValueError("the fake adds Started, UserMessage and Done itself")
        self._script = list(events)

    def chat(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> AsyncIterator[AgentEvent]:
        self.calls.append(("chat", (principal, visitor, request)))
        return self._chat(principal, request)

    async def conversation(
        self, principal: Principal, conversation_id: ConversationId
    ) -> ConversationView:
        self.calls.append(("conversation", (principal, conversation_id)))
        if self._owners.get(conversation_id) != principal.workspace_id:
            raise NotFoundError
        return ConversationView(
            conversation_id=conversation_id, messages=list(self._messages[conversation_id])
        )

    def replay(self, locale: Locale) -> AsyncIterator[AgentEvent]:
        self.calls.append(("replay", (locale,)))
        return self._replay(locale)

    async def _chat(self, principal: Principal, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        conversation_id = request.conversation_id
        if conversation_id is None:
            conversation_id = ConversationId(f"conversation-{len(self._owners) + 1}")
            self._owners[conversation_id] = principal.workspace_id
        elif self._owners.get(conversation_id) != principal.workspace_id:
            raise NotFoundError
        events = list(self._script)
        user_id, assistant_id = self._message_id(), self._message_id()
        now = self._clock.now()
        self._messages.setdefault(conversation_id, []).extend(
            [
                MessageView(
                    message_id=user_id,
                    role="user",
                    text=request.message,
                    tools=[],
                    flagged=[],
                    created_at=now,
                ),
                MessageView(
                    message_id=assistant_id,
                    role="assistant",
                    text="".join(event.text for event in events if isinstance(event, TextDelta)),
                    tools=[event for event in events if isinstance(event, ToolFinished)],
                    flagged=[
                        value
                        for event in events
                        if isinstance(event, GroundingFlagged)
                        for value in event.values
                    ],
                    created_at=now,
                ),
            ]
        )
        yield Started(conversation_id=conversation_id, message_id=assistant_id)
        for event in events:
            yield event
        yield self._done(conversation_id, assistant_id)

    async def _replay(self, locale: Locale) -> AsyncIterator[AgentEvent]:
        conversation_id = ConversationId(f"replay-{locale}")
        message_id = f"replay-{locale}-1"
        yield Started(conversation_id=conversation_id, message_id=message_id)
        yield UserMessage(text=REPLAY_REQUEST)
        for event in self._script:
            yield event
        yield self._done(conversation_id, message_id)

    def _message_id(self) -> str:
        self._count += 1
        return f"message-{self._count}"

    @staticmethod
    def _done(conversation_id: ConversationId, message_id: str) -> Done:
        return Done(
            conversation_id=conversation_id,
            message_id=message_id,
            stop_reason="end_turn",
            prompt_version=PROMPT_VERSION,
        )
