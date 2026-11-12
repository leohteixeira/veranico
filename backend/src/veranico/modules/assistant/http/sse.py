"""Server-sent events: one `AgentEvent` as `event: <name>\\ndata: <json>\\n\\n`.

The JSON is one line (a line break inside a string is escaped), so an event is always one
`data:` field. Text is UTF-8 and is not escaped to ASCII.
"""

from veranico.modules.assistant.application.replay import EVENT_NAMES
from veranico.modules.assistant.contracts import AgentEvent


def encode(event: AgentEvent) -> bytes:
    name = EVENT_NAMES[type(event)]
    return f"event: {name}\ndata: {event.model_dump_json()}\n\n".encode()
