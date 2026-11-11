"""The stored conversation: what a turn appends and what makes a history a valid model input.

A conversation is an ordered list of entries. `seq` orders them inside the conversation and
`turn` names the user turn they belong to. A user message opens a turn; each model call of the
turn that produced something is one `AssistantStep` (its text and the tool calls it asked for),
followed by one `ToolResultEntry` per tool call, in the order of the calls.

Every full tool result is stored (SPEC 9.2). Compaction never touches these entries: it builds
shortened copies for one prompt (`compaction.py`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class UserEntry:
    seq: int
    turn: int
    text: str


@dataclass(frozen=True, slots=True)
class AssistantStep:
    seq: int
    turn: int
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResultEntry:
    seq: int
    turn: int
    call_id: str
    tool: str
    status: Literal["ok", "error"]
    # "ok": the tool's output model, serialised, in full.
    # "error": the tool error as the model sees it, `{error_code, message, retryable}`.
    result: Mapping[str, object]


Entry = UserEntry | AssistantStep | ToolResultEntry


def is_valid_history(entries: Sequence[Entry]) -> bool:
    """True when the entries can be sent to the model as they are.

    The model API rejects a tool call without its result and a result without its call, so:
    `seq` strictly increases; a step's tool calls are answered by the entries that directly
    follow it, one result per call, in the same order and with the same tool name; no result
    appears anywhere else; and call identifiers are never reused.
    """
    last_seq: int | None = None
    pending: list[ToolCall] = []
    seen_calls: set[str] = set()
    for entry in entries:
        if last_seq is not None and entry.seq <= last_seq:
            return False
        last_seq = entry.seq
        if isinstance(entry, ToolResultEntry):
            if not pending:
                return False
            call = pending.pop(0)
            if (entry.call_id, entry.tool) != (call.call_id, call.tool):
                return False
            continue
        if pending:
            return False
        if isinstance(entry, AssistantStep):
            for call in entry.tool_calls:
                if call.call_id in seen_calls:
                    return False
                seen_calls.add(call.call_id)
            pending = list(entry.tool_calls)
    return not pending
