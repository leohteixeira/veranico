"""Response class of the streaming `assistant` routes: it names the media type in OpenAPI.

The events of the stream are the `AgentEvent` models of the contract, sent as
`event: <name>\\ndata: <json>\\n\\n`. They are registered in the OpenAPI components by the
application factory, because OpenAPI 3.1 cannot describe the items of an event stream.
"""

from fastapi.responses import StreamingResponse


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"
