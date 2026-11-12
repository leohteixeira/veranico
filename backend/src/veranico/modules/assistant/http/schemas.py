"""Response class of the streaming `assistant` routes: it names the media type in OpenAPI.

The events of the stream are the `AgentEvent` models of the contract, sent as
`event: <name>\\ndata: <json>\\n\\n`. They are registered in the OpenAPI components by the
application factory, because OpenAPI 3.1 cannot describe the items of an event stream.

The class also closes its content when the response ends for any reason. Starlette stops
reading the content when the client disconnects (it cancels the read, or a send fails) and
does not close it, so an open turn would otherwise be closed only when the generator is
garbage-collected. Read in the installed Starlette 1.10.0 (`StreamingResponse.__call__`) on
2026-11-11; the server (uvicorn 0.54.0) announces ASGI spec 2.3, which is the cancelling path.
"""

from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                await close()
