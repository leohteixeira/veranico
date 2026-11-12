"""What every `ConversationStore` does. The memory store and the Firestore store both run it.

A subclass provides two fixtures: `clock` (a `FixedClock`) and `stores`, two stores over the
same data, as two instances of the service would hold. Conversation ids are random, so the
tests share an emulator with other runs without clearing anything.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes.builders import priced_cover
from veranico.modules.assistant.application.ports import ConversationStore
from veranico.modules.assistant.application.views import conversation_view
from veranico.modules.assistant.contracts import ToolError
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
    is_valid_history,
)
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import ConflictError, NotFoundError
from veranico.shared.kernel.ids import ConversationId, WorkspaceId

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
TTL = timedelta(days=14)
LEASE = timedelta(minutes=3)
WS = WorkspaceId("ws-store-1")
OTHER = WorkspaceId("ws-store-2")

PRICED: dict[str, object] = {
    "quote_id": "Q-7K3M9P",
    "priced": priced_cover().model_dump(mode="json"),
    # Shapes a document database could alter: a float that is a whole number, a key with a
    # dot, non-ASCII text, an empty list, a null.
    "odd": {"whole": 150.0, "a.b": 1, "nome": "Três Pontas", "none": None, "empty": []},
}
ERROR = {"error_code": "invalid_cover", "message": "exit above trigger", "retryable": False}


def turn_entries(turn: int, first_seq: int) -> list[Entry]:
    """A user message, a step with two tool calls, their results and the closing text."""
    return [
        UserEntry(
            seq=first_seq, turn=turn, text="Price it", locale="pt-BR", map_point=(-21.37, -45.51)
        ),
        AssistantStep(
            seq=first_seq + 1,
            turn=turn,
            text="Pricing.",
            tool_calls=(
                ToolCall(
                    call_id=f"c{turn}a", tool="price_cover", arguments={"limit_cents": 30_000_000}
                ),
                ToolCall(call_id=f"c{turn}b", tool="backtest_index", arguments={"trigger": 150.0}),
            ),
        ),
        ToolResultEntry(
            seq=first_seq + 2,
            turn=turn,
            call_id=f"c{turn}a",
            tool="price_cover",
            status="ok",
            result=PRICED,
            summary={
                "code": "tool.price_cover",
                "params": {"quote_id": "Q-7K3M9P", "premium_cents": 5},
            },
            duration_ms=1840,
        ),
        ToolResultEntry(
            seq=first_seq + 3,
            turn=turn,
            call_id=f"c{turn}b",
            tool="backtest_index",
            status="error",
            result=ERROR,
            summary={"code": "tool.error", "params": {"error_code": "invalid_cover"}},
            duration_ms=12,
        ),
        AssistantStep(seq=first_seq + 4, turn=turn, text="Quote Q-7K3M9P is a draft."),
    ]


class ConversationStoreContract:
    @pytest.mark.req("R-9.2-1")
    async def test_conversation_is_readable_from_a_second_client(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "pt-BR")
        turn = await first.claim_turn(WS, conversation_id, "m-1")
        await first.append(conversation_id, turn_entries(turn, 1))
        await first.finish_turn(conversation_id, "m-1", [], 1_200, "v1")

        # Any instance continues the conversation: it reads the history and takes the next turn.
        state = await second.load(WS, conversation_id)
        next_turn = await second.claim_turn(WS, conversation_id, "m-2")

        assert state.conversation_id == conversation_id
        assert state.workspace_id == WS
        assert state.locale == "pt-BR"
        assert state.entries == tuple(turn_entries(1, 1))
        assert state.total_tokens == 1_200
        assert (turn, next_turn) == (1, 2)

    @pytest.mark.req("R-9.2-1")
    async def test_other_workspace_gets_not_found(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")

        with pytest.raises(NotFoundError):
            await store.load(OTHER, conversation_id)
        with pytest.raises(NotFoundError):
            await store.claim_turn(OTHER, conversation_id, "m-1")
        # The owner is untouched by the refused claim.
        assert await store.claim_turn(WS, conversation_id, "m-1") == 1

    async def test_unknown_conversation_is_not_found(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        store, _ = stores
        unknown = ConversationId("0" * 32)

        with pytest.raises(NotFoundError):
            await store.load(WS, unknown)
        with pytest.raises(NotFoundError):
            await store.claim_turn(WS, unknown, "m-1")
        with pytest.raises(NotFoundError):
            await store.append(unknown, turn_entries(1, 1))

    async def test_second_claim_while_active_is_conflict(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "en")
        await first.claim_turn(WS, conversation_id, "m-1")

        with pytest.raises(ConflictError):
            await second.claim_turn(WS, conversation_id, "m-2")

        # Releasing the claim lets the next turn in.
        await first.finish_turn(conversation_id, "m-1", [], 0, "v1")
        assert await second.claim_turn(WS, conversation_id, "m-2") == 2

    async def test_expired_claim_can_be_taken(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "en")
        await first.claim_turn(WS, conversation_id, "m-crashed")

        clock.advance(LEASE - timedelta(seconds=1))
        with pytest.raises(ConflictError):
            await second.claim_turn(WS, conversation_id, "m-2")
        clock.advance(timedelta(seconds=1))

        assert await second.claim_turn(WS, conversation_id, "m-2") == 2

    async def test_appending_renews_the_lease(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "en")
        await first.claim_turn(WS, conversation_id, "m-1")

        clock.advance(LEASE - timedelta(seconds=1))
        await first.append(conversation_id, [UserEntry(seq=1, turn=1, text="still working")])
        clock.advance(LEASE - timedelta(seconds=1))

        with pytest.raises(ConflictError):
            await second.claim_turn(WS, conversation_id, "m-2")

    async def test_a_late_finish_does_not_release_the_next_turns_claim(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-slow")
        clock.advance(LEASE)
        await store.claim_turn(WS, conversation_id, "m-2")

        await store.finish_turn(conversation_id, "m-slow", [], 10, "v1")

        with pytest.raises(ConflictError):
            await store.claim_turn(WS, conversation_id, "m-3")

    @pytest.mark.req("R-9.2-2")
    async def test_step_and_its_tool_results_are_written_atomically(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-1")
        user, step, first_result, second_result, closing = turn_entries(1, 1)
        await store.append(conversation_id, [user])

        # One write for the step and both results: the history is valid before and after it.
        assert is_valid_history((await store.load(WS, conversation_id)).entries)
        await store.append(conversation_id, [step, first_result, second_result])
        after = (await store.load(WS, conversation_id)).entries
        assert after == (user, step, first_result, second_result)
        assert is_valid_history(after)

        # A write that cannot land as a whole lands not at all: `closing` is new, but the
        # entry beside it reuses a stored seq.
        clash = AssistantStep(seq=first_result.seq, turn=1, text="overwrite")
        with pytest.raises(ConflictError):
            await store.append(conversation_id, [closing, clash])
        assert (await store.load(WS, conversation_id)).entries == after

    @pytest.mark.req("R-9.2-2")
    async def test_full_tool_results_are_stored_untouched(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "en")
        await first.claim_turn(WS, conversation_id, "m-1")
        entries = turn_entries(1, 1)

        await first.append(conversation_id, entries)

        stored = (await second.load(WS, conversation_id)).entries
        assert stored == tuple(entries)
        result = stored[2]
        assert isinstance(result, ToolResultEntry)
        assert result.result == PRICED
        priced = result.result["priced"]
        assert isinstance(priced, dict)
        assert len(priced["backtest"]["seasons"]) == len(PRICED["priced"]["backtest"]["seasons"])  # type: ignore[index]  # PRICED is typed as object values; the shape is known here
        odd = result.result["odd"]
        assert isinstance(odd, dict)
        assert type(odd["whole"]) is float  # 150.0 did not come back as the integer 150
        user = stored[0]
        assert isinstance(user, UserEntry)
        assert (user.locale, user.map_point) == ("pt-BR", (-21.37, -45.51))

    @pytest.mark.req("R-9.3-8")
    @pytest.mark.req("R-9.5-2")
    async def test_flagged_marker_and_prompt_version_are_stored_on_the_turn(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        first, second = stores
        conversation_id = await first.create(WS, "en")
        await first.claim_turn(WS, conversation_id, "m-1")
        clock.advance(timedelta(seconds=20))

        await first.finish_turn(conversation_id, "m-1", ["R$ 2,070.00", "3%"], 900, "v1")
        await first.claim_turn(WS, conversation_id, "m-2")
        await first.finish_turn(conversation_id, "m-2", [], 100, "v2")

        state = await second.load(WS, conversation_id)
        assert [(t.turn, t.message_id, t.flagged, t.prompt_version) for t in state.turns] == [
            (1, "m-1", ("R$ 2,070.00", "3%"), "v1"),
            (2, "m-2", (), "v2"),
        ]
        assert state.turns[0].started_at == NOW
        assert state.turns[0].finished_at == NOW + timedelta(seconds=20)
        assert state.total_tokens == 1_000

    async def test_an_unfinished_turn_is_recorded_as_started(
        self, stores: tuple[ConversationStore, ConversationStore]
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-1")

        [record] = (await store.load(WS, conversation_id)).turns

        assert (record.finished_at, record.flagged, record.prompt_version) == (None, (), None)

    @pytest.mark.req("R-14-1")
    async def test_an_expired_conversation_is_not_found(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        # The TTL policy deletes within about a day; until then the store filters.
        store, _ = stores
        conversation_id = await store.create(WS, "en")

        clock.advance(TTL - timedelta(seconds=1))
        assert (await store.load(WS, conversation_id)).entries == ()
        clock.advance(timedelta(seconds=1))

        with pytest.raises(NotFoundError):
            await store.load(WS, conversation_id)
        with pytest.raises(NotFoundError):
            await store.claim_turn(WS, conversation_id, "m-1")

    async def test_view_folds_a_turn_into_one_assistant_message(
        self, stores: tuple[ConversationStore, ConversationStore], clock: FixedClock
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-1")
        await store.append(conversation_id, turn_entries(1, 1))
        clock.advance(timedelta(seconds=20))
        await store.finish_turn(conversation_id, "m-1", ["R$ 9"], 10, "v1")
        await store.claim_turn(WS, conversation_id, "m-2")
        await store.append(conversation_id, [UserEntry(seq=6, turn=2, text="And now?")])

        view = conversation_view(await store.load(WS, conversation_id))

        assert view.conversation_id == conversation_id
        user, assistant, pending = view.messages  # the second turn has no answer yet
        assert (user.message_id, user.role, user.text) == ("m-1:user", "user", "Price it")
        assert (user.tools, user.flagged, user.created_at) == ([], [], NOW)
        assert (assistant.message_id, assistant.role) == ("m-1", "assistant")
        assert assistant.text == "Pricing.\n\nQuote Q-7K3M9P is a draft."
        assert assistant.flagged == ["R$ 9"]
        assert assistant.created_at == NOW + timedelta(seconds=20)
        ok, failed = assistant.tools
        assert (ok.call_id, ok.tool, ok.status, ok.duration_ms) == (
            "c1a",
            "price_cover",
            "ok",
            1840,
        )
        assert ok.summary == Coded(
            code="tool.price_cover", params={"quote_id": "Q-7K3M9P", "premium_cents": 5}
        )
        assert ok.result == PRICED
        assert ok.error is None
        assert (failed.status, failed.result) == ("error", None)
        assert failed.error == ToolError(
            error_code="invalid_cover", message="exit above trigger", retryable=False
        )
        assert failed.summary == Coded(code="tool.error", params={"error_code": "invalid_cover"})
        assert (pending.message_id, pending.role, pending.text) == ("m-2:user", "user", "And now?")
