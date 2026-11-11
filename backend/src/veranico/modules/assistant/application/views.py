"""The stored conversation as the interface restores it (`GET /conversations/{id}`).

A turn folds into one user message and one assistant message: the text of all its steps, the
tools it ran and the figures the grounding check flagged. The assistant message carries the
turn's `message_id`, the one the stream announced in `started`; the user message is
`<message_id>:user`.
"""

from veranico.modules.assistant.application.ports import ConversationState
from veranico.modules.assistant.contracts import (
    ConversationView,
    MessageView,
    ToolError,
    ToolFinished,
)
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    ToolResultEntry,
    UserEntry,
)
from veranico.shared.kernel.coded import Coded

# Between the texts of two steps of one turn. The stream sends the same separator.
STEP_SEPARATOR = "\n\n"


def conversation_view(state: ConversationState) -> ConversationView:
    messages: list[MessageView] = []
    for record in state.turns:
        entries = [entry for entry in state.entries if entry.turn == record.turn]
        for entry in entries:
            if isinstance(entry, UserEntry):
                messages.append(
                    MessageView(
                        message_id=f"{record.message_id}:user",
                        role="user",
                        text=entry.text,
                        tools=[],
                        flagged=[],
                        created_at=record.started_at,
                    )
                )
        steps = [entry for entry in entries if isinstance(entry, AssistantStep)]
        results = [entry for entry in entries if isinstance(entry, ToolResultEntry)]
        if not steps and not results:
            continue  # the turn ended before the model produced anything
        messages.append(
            MessageView(
                message_id=record.message_id,
                role="assistant",
                text=STEP_SEPARATOR.join(step.text for step in steps if step.text),
                tools=[tool_finished(result) for result in results],
                flagged=list(record.flagged),
                created_at=record.finished_at or record.started_at,
            )
        )
    return ConversationView(conversation_id=state.conversation_id, messages=messages)


def tool_finished(entry: ToolResultEntry) -> ToolFinished:
    """The `tool_finished` event of a stored result, as the stream sent it."""
    summary = entry.summary or {"code": f"tool.{entry.tool}", "params": {}}
    failed = entry.status == "error"
    return ToolFinished(
        call_id=entry.call_id,
        tool=entry.tool,
        status=entry.status,
        duration_ms=entry.duration_ms,
        summary=Coded.model_validate(summary),
        result=None if failed else dict(entry.result),
        error=ToolError.model_validate(entry.result) if failed else None,
    )
