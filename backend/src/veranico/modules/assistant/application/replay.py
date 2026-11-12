"""The recorded conversation the interface plays when a visitor may not chat (SPEC 9.6).

A recording is a file per locale, `replays/<locale>.jsonl`. Its first line is metadata about
the recording (prompt version, model, date, data source); every other line is one event of
the chat stream, `{"event": <name>, "data": {...}}`. Each recorded turn is its `started`, one
`user_message` with the request of that turn, the events of the turn and its `done`.

Serving a replay reads these files and nothing else: no module is called, nothing is written.
"""

import json
from collections.abc import AsyncGenerator, Mapping
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final, get_args

from pydantic import BaseModel

from veranico.modules.assistant.contracts import (
    AgentEvent,
    ApprovalRequired,
    Done,
    GroundingFlagged,
    Started,
    StreamError,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UserMessage,
)
from veranico.shared.kernel.ids import Locale

# The wire name of each event (contracts section 8).
EVENT_NAMES: Final[Mapping[type[BaseModel], str]] = {
    Started: "started",
    UserMessage: "user_message",
    TextDelta: "text_delta",
    ToolStarted: "tool_started",
    ToolFinished: "tool_finished",
    ApprovalRequired: "approval_required",
    GroundingFlagged: "grounding_flagged",
    StreamError: "error",
    Done: "done",
}
_EVENT_TYPES: Final = {name: model for model, name in EVENT_NAMES.items()}

LOCALES: Final[tuple[Locale, ...]] = get_args(Locale)


def parse_recording(text: str) -> tuple[dict[str, object], tuple[AgentEvent, ...]]:
    """The metadata and the events of a recording file. Raises on anything malformed."""
    first, *lines = [line for line in text.splitlines() if line.strip()]
    metadata = json.loads(first)
    if not isinstance(metadata, dict) or "event" in metadata:
        raise ValueError("the first line of a recording is its metadata")
    events: list[AgentEvent] = []
    for line in lines:
        record = json.loads(line)
        model = _EVENT_TYPES[record["event"]]
        events.append(model.model_validate(record["data"]))  # type: ignore[arg-type]  # every model of the table is a member of AgentEvent
    return metadata, tuple(events)


class Replays:
    """The recordings of every locale, read once when the module is built."""

    def __init__(self, directory: Traversable | None = None) -> None:
        root = directory or resources.files("veranico.modules.assistant.replays")
        self._events = {
            locale: parse_recording(root.joinpath(f"{locale}.jsonl").read_text(encoding="utf-8"))[1]
            for locale in LOCALES
        }

    def events(self, locale: Locale) -> tuple[AgentEvent, ...]:
        return self._events[locale]

    async def stream(self, locale: Locale) -> AsyncGenerator[AgentEvent]:
        for event in self._events[locale]:
            yield event
