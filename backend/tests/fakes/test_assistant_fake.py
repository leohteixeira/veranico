import pytest

from tests.fakes.access import FakeAccessFacade
from tests.fakes.assistant import PROMPT_VERSION, REPLAY_REQUEST, FakeAssistantFacade
from veranico.modules.assistant.contracts import (
    AgentEvent,
    ApprovalRequired,
    ChatRequest,
    Done,
    GroundingFlagged,
    Started,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UserMessage,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import ConversationId, QuoteId, SubmissionId, WorkspaceId
from veranico.shared.kernel.principal import Principal

BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
OTHER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")
VISITOR = FakeAccessFacade().visitor("203.0.113.9", None)
TOOL = ToolFinished(
    call_id="call-1",
    tool="price_cover",
    status="ok",
    duration_ms=5,
    summary=Coded(code="tool.price_cover", params={"premium_cents": 500_000}),
    result={"quote_id": "Q-000001"},
    error=None,
)
SCRIPT: list[AgentEvent] = [
    ToolStarted(call_id="call-1", tool="price_cover", arguments={"limit_cents": 10_000_000}),
    TOOL,
    TextDelta(text="The premium is "),
    TextDelta(text="R$ 5,000.00."),
    GroundingFlagged(message_id="message-2", values=["7%"]),
    ApprovalRequired(approval_id=SubmissionId("S-000001"), quote_id=QuoteId("Q-000001")),
]


def request(message: str = "hi", conversation_id: str | None = None) -> ChatRequest:
    return ChatRequest(
        conversation_id=ConversationId(conversation_id) if conversation_id else None,
        message=message,
        locale="en",
    )


async def test_chat_yields_the_script_between_started_and_done() -> None:
    assistant = FakeAssistantFacade()
    assistant.script(SCRIPT)

    events = [event async for event in assistant.chat(BROWSER, VISITOR, request())]

    assert isinstance(events[0], Started)
    assert events[1:-1] == SCRIPT
    assert events[-1] == Done(
        conversation_id=events[0].conversation_id,
        message_id=events[0].message_id,
        stop_reason="end_turn",
        prompt_version=PROMPT_VERSION,
    )
    assert not any(isinstance(event, UserMessage) for event in events)


async def test_the_default_stream_still_starts_with_started_and_ends_with_done() -> None:
    events = [event async for event in FakeAssistantFacade().chat(BROWSER, VISITOR, request())]

    assert isinstance(events[0], Started)
    assert isinstance(events[-1], Done)
    assert len(events) == 3


async def test_replay_carries_the_recorded_request_as_a_user_message() -> None:
    assistant = FakeAssistantFacade()
    assistant.script(SCRIPT)

    events = [event async for event in assistant.replay("pt-BR")]

    assert isinstance(events[0], Started)
    assert events[1] == UserMessage(text=REPLAY_REQUEST)
    assert events[2:-1] == SCRIPT
    assert isinstance(events[-1], Done)
    assert events[-1].conversation_id == events[0].conversation_id


def test_a_script_may_not_contain_the_events_the_fake_adds() -> None:
    assistant = FakeAssistantFacade()

    for event in (
        Started(conversation_id=ConversationId("c"), message_id="m"),
        UserMessage(text="x"),
        Done(
            conversation_id=ConversationId("c"),
            message_id="m",
            stop_reason="end_turn",
            prompt_version="p",
        ),
    ):
        with pytest.raises(ValueError, match="adds"):
            assistant.script([event])


async def test_conversation_returns_what_was_streamed() -> None:
    assistant = FakeAssistantFacade()
    assistant.script(SCRIPT)
    first = [event async for event in assistant.chat(BROWSER, VISITOR, request("price it"))]
    started = first[0]
    assert isinstance(started, Started)
    assistant.script([TextDelta(text="Done.")])
    second = [
        event
        async for event in assistant.chat(
            BROWSER, VISITOR, request("thanks", started.conversation_id)
        )
    ]
    assert isinstance(second[0], Started)
    assert second[0].conversation_id == started.conversation_id

    view = await assistant.conversation(BROWSER, started.conversation_id)

    assert view.conversation_id == started.conversation_id
    assert [(m.role, m.text) for m in view.messages] == [
        ("user", "price it"),
        ("assistant", "The premium is R$ 5,000.00."),
        ("user", "thanks"),
        ("assistant", "Done."),
    ]
    assert view.messages[1].message_id == started.message_id
    assert view.messages[1].tools == [TOOL]
    assert view.messages[1].flagged == ["7%"]
    assert len({message.message_id for message in view.messages}) == 4


async def test_a_conversation_of_another_workspace_is_not_found() -> None:
    assistant = FakeAssistantFacade()
    events = [event async for event in assistant.chat(BROWSER, VISITOR, request())]
    started = events[0]
    assert isinstance(started, Started)

    with pytest.raises(NotFoundError):
        await assistant.conversation(OTHER, started.conversation_id)
    with pytest.raises(NotFoundError):
        await assistant.conversation(BROWSER, ConversationId("unknown"))
    with pytest.raises(NotFoundError):
        _ = [
            event
            async for event in assistant.chat(
                OTHER, VISITOR, request("hi", started.conversation_id)
            )
        ]


async def test_calls_are_recorded_when_the_method_is_called() -> None:
    assistant = FakeAssistantFacade()
    chat_request = request()

    assistant.chat(BROWSER, VISITOR, chat_request)  # not iterated
    assistant.replay("en")

    assert assistant.calls == [("chat", (BROWSER, VISITOR, chat_request)), ("replay", ("en",))]
