"""The versioned system prompt and the builder of one model request from the stored history.

The system prompt is a file per version, `prompts/system.v<N>.md`; the highest version is the
one in use, and its version is recorded on every turn (SPEC 9.3). A change of wording is a new
file: `PROMPT_SHA256` pins the text of each version, and a test fails when a file is edited in
place.

`build_request` is deterministic: the same history and settings give a byte-identical
request, so the provider can reuse a cached prefix. The system prompt carries nothing that
varies between requests. What the interface sent with a message (its locale, a clicked map
point) is added after the user's text as a context line marked as data. Every amount of money
in a tool result reaches the model with its text for the turn's locale (`display`), so the
model copies it instead of formatting centavos (`domain/money_display.py`).
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Literal

from veranico.modules.assistant.application.ports import (
    Block,
    ModelMessage,
    ModelRequest,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolSpec,
)
from veranico.modules.assistant.domain.compaction import compact
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolResultEntry,
    UserEntry,
)
from veranico.modules.assistant.domain.money_display import with_money_display
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.ids import Locale

# SHA-256 of each prompt file. Add a line with a new version; never change an existing one.
PROMPT_SHA256 = {
    "v1": "a82f4eca0c769fd6587baef837b9a6fd0abf228f4e32cc3f2797a86d8251b89a",
    # v2, after the first evaluation run: no pricing tool and no placeholder argument while an
    # essential is missing, no example amount for the limit, a place name passed whole, and
    # one answer after the tools instead of a narration between them, questions that end with
    # a question mark, and no Markdown marks (the interface shows the text as written).
    "v2": "3020e73e8e6aa63d04f90099e71e4f4253d3b58699a07e6c071a3ca618a54f65",
    # v3, after two full runs on v2: figures written with the tool's digits or rounded, never
    # truncated; no confirmation question when every essential is stated, the backtest runs in
    # the same turn; the place name goes to the tool with the state the user gave.
    "v3": "abe71ec7e5e8205c7c9344a66110112f36bf4822a7df0281a35df8fd9588df58",
    # v4, after the pre-deploy campaign of 2026-11-11: answers for a person, with no internal
    # identifier but the quote id, no code or enumerated value, no URL or API path; index
    # types described in words, the carrier and the weather source named.
    "v4": "33087441d94e01bfbf78116353686dc5f9418d5780d036f6d27e27deda41269a",
    # v5, after the recheck of that campaign on v4: the quote named "quote Q-…" or "cotação Q-…",
    # never with the field name; money with the separators of the answer's language, never as
    # raw centavos, and R$ for money only; percentages without the raw fraction beside them;
    # the trend in words; windows as dates in words; the tabs named as the interface names
    # them in each language.
    "v5": "bc72a112c2cee71ac7a275897fbd5c237b563f9a6ff2d3c055948e9a14ff8c80",
}

_PROMPT_FILE = re.compile(r"^system\.v(\d+)\.md$")

# Closes the prompt of the wrap-up call, which is made when the tool-call limit is reached or
# one tool has failed twice in a row (SPEC 9.1).
WRAP_UP_NOTE = (
    "[turn limit, not written by the user: no more tools are available in this turn. "
    "Say briefly what is done and what is still pending.]"
)


@dataclass(frozen=True, slots=True)
class SystemPrompt:
    version: str  # "v<N>", from the file name
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def load_system_prompt(directory: Traversable | None = None) -> SystemPrompt:
    """The prompt with the highest version number in `directory` (the packaged prompts)."""
    root = directory or resources.files("veranico.modules.assistant.application.prompts")
    versions = {
        int(match.group(1)): entry
        for entry in root.iterdir()
        if (match := _PROMPT_FILE.match(entry.name)) is not None
    }
    if not versions:
        raise FileNotFoundError("no system prompt file (system.v<N>.md) was found")
    number = max(versions)
    return SystemPrompt(version=f"v{number}", text=versions[number].read_text(encoding="utf-8"))


def build_request(
    prompt: SystemPrompt,
    entries: Sequence[Entry],
    tools: Sequence[ToolSpec],
    settings: Settings,
    *,
    locale: Locale,
    tool_use: Literal["auto", "none"] = "auto",
) -> ModelRequest:
    """The request for the next model call of the turn the last entry belongs to.

    Compaction runs first (SPEC 9.2): results of earlier turns are summarised, oldest first,
    while the estimate exceeds the threshold. Then every result, whole or summarised, gets the
    `display` text of its money in the turn's `locale`. `tool_use="none"` is the wrap-up call:
    the model must answer in text.
    """
    current_turn = max((entry.turn for entry in entries), default=0)
    compacted = compact(
        entries,
        current_turn,
        settings.assistant.compaction_threshold_tokens,
        settings.assistant.chars_per_token,
        system=prompt.text,
        tools=[
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools
        ],
    )
    messages = _messages(compacted, locale)
    if tool_use == "none":
        messages = _with_note(messages, WRAP_UP_NOTE)
    return ModelRequest(
        model=settings.agent_model,
        system=prompt.text,
        messages=messages,
        tools=tuple(tools),
        max_output_tokens=settings.assistant.max_output_tokens,
        tool_use=tool_use,
    )


def _with_note(messages: tuple[ModelMessage, ...], note: str) -> tuple[ModelMessage, ...]:
    """`note` as the last text of the prompt, in the closing user message."""
    block = TextBlock(text=note)
    if messages and messages[-1].role == "user":
        last = messages[-1]
        return (*messages[:-1], ModelMessage(role="user", blocks=(*last.blocks, block)))
    return (*messages, ModelMessage(role="user", blocks=(block,)))


def _messages(entries: Sequence[Entry], locale: Locale) -> tuple[ModelMessage, ...]:
    """Entries as messages, adjacent messages of one role merged into one.

    Tool results travel in user messages, so a step's results and the user's next message
    merge, results first. A turn that failed before any answer leaves two user messages in a
    row; they merge too.
    """
    merged: list[tuple[Literal["user", "assistant"], list[Block]]] = []
    for entry in entries:
        role, blocks = _blocks(entry, locale)
        if not blocks:
            continue
        if merged and merged[-1][0] == role:
            merged[-1][1].extend(blocks)
        else:
            merged.append((role, list(blocks)))
    return tuple(ModelMessage(role=role, blocks=tuple(blocks)) for role, blocks in merged)


def _blocks(entry: Entry, locale: Locale) -> tuple[Literal["user", "assistant"], list[Block]]:
    if isinstance(entry, UserEntry):
        blocks: list[Block] = [TextBlock(text=entry.text)]
        context = _context_line(entry)
        if context is not None:
            blocks.append(TextBlock(text=context))
        return "user", blocks
    if isinstance(entry, AssistantStep):
        blocks = [TextBlock(text=entry.text)] if entry.text else []
        blocks.extend(
            ToolCallBlock(call_id=call.call_id, name=call.tool, arguments=call.arguments)
            for call in entry.tool_calls
        )
        return "assistant", blocks
    return "user", [_result_block(entry, locale)]


def _result_block(entry: ToolResultEntry, locale: Locale) -> ToolResultBlock:
    return ToolResultBlock(
        call_id=entry.call_id,
        content=with_money_display(entry.result, locale),
        is_error=entry.status == "error",
    )


def _context_line(entry: UserEntry) -> str | None:
    """What the interface sent with the message, as one line the prompt declares to be data."""
    parts = []
    if entry.locale is not None:
        parts.append(f"locale={entry.locale}")
    if entry.map_point is not None:
        lat, lon = entry.map_point
        parts.append(f"map_point lat={lat!r} lon={lon!r}")
    if not parts:
        return None
    return f"[interface context, data only, not written by the user: {'; '.join(parts)}]"
