"""A stored history is a valid model input only when calls and results pair up (SPEC 9.2)."""

import pytest

from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
    is_valid_history,
)

pytestmark = pytest.mark.req("R-9.2-2")


def call(call_id: str, tool: str = "resolve_location") -> ToolCall:
    return ToolCall(call_id=call_id, tool=tool, arguments={"query": "Varginha"})


def result(seq: int, call_id: str, tool: str = "resolve_location") -> ToolResultEntry:
    return ToolResultEntry(
        seq=seq, turn=1, call_id=call_id, tool=tool, status="ok", result={"label": "Varginha"}
    )


VALID: tuple[Entry, ...] = (
    UserEntry(seq=1, turn=1, text="Coffee farm near Varginha"),
    AssistantStep(seq=2, turn=1, text="Let me look.", tool_calls=(call("c1"), call("c2", "b"))),
    result(3, "c1"),
    result(4, "c2", "b"),
    AssistantStep(seq=5, turn=1, text="Found it."),
)


def test_history_is_valid_only_when_every_tool_call_has_its_result() -> None:
    assert is_valid_history(VALID)
    assert not is_valid_history(VALID[:3])  # the second call has no result
    assert not is_valid_history(VALID[:2])  # neither call has one
    assert not is_valid_history((*VALID[:3], VALID[4]))  # a step before the results are complete


def test_empty_and_text_only_histories_are_valid() -> None:
    assert is_valid_history(())
    assert is_valid_history((VALID[0],))
    assert is_valid_history((VALID[0], AssistantStep(seq=2, turn=1, text="Which window?")))


def test_two_user_messages_in_a_row_are_valid() -> None:
    # A turn that failed before any answer leaves its user message without a step.
    history = (VALID[0], UserEntry(seq=2, turn=2, text="Are you there?"))

    assert is_valid_history(history)


def test_a_result_without_its_call_is_invalid() -> None:
    assert not is_valid_history((VALID[0], result(2, "c9")))
    assert not is_valid_history((*VALID, result(6, "c1")))


def test_results_must_answer_the_calls_in_order_with_the_same_tool() -> None:
    step = VALID[1]

    assert not is_valid_history((VALID[0], step, result(3, "c2", "b"), result(4, "c1")))
    assert not is_valid_history((VALID[0], step, result(3, "c1"), result(4, "c2", "other")))


def test_a_user_message_between_a_call_and_its_result_is_invalid() -> None:
    history = (*VALID[:3], UserEntry(seq=4, turn=2, text="hello"), result(5, "c2", "b"))

    assert not is_valid_history(history)


def test_seq_must_strictly_increase() -> None:
    assert not is_valid_history((VALID[0], AssistantStep(seq=1, turn=1, text="Hi")))
    assert not is_valid_history((VALID[4], VALID[0]))


def test_a_reused_call_id_is_invalid() -> None:
    again = AssistantStep(seq=6, turn=1, text="", tool_calls=(call("c1"),))

    assert not is_valid_history((*VALID, again, result(7, "c1")))


def test_entries_are_immutable() -> None:
    with pytest.raises(AttributeError):
        VALID[0].seq = 9  # type: ignore[misc]  # the assignment is the point of the test
