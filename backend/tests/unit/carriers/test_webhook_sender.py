import asyncio

import httpx
import pytest

from veranico.modules.carriers.application.ports import SendResult, WebhookSender
from veranico.modules.carriers.infrastructure.webhook_sender import HttpxWebhookSender

pytestmark = pytest.mark.req("R-7-3")

URL = "http://carrier.test/carrier/v1/submissions"
HEADERS = {"Content-Type": "application/json", "Veranico-Timestamp": "1794000000"}
BODY = b'{"event_id": "e-1",  "spaced":\ttrue, "bytes": "\xc3\xa9"}'


class Handler:
    """Plays the carrier behind `httpx.MockTransport` and keeps every request it saw."""

    def __init__(self, response: httpx.Response | Exception, *, delay: float = 0.0) -> None:
        self._response = response
        self._delay = delay
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _sender(
    handler: Handler,
    *,
    connect: float = 2.0,
    total: float = 10.0,
    follow_redirects: bool = False,
) -> HttpxWebhookSender:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
    )
    return HttpxWebhookSender(client, connect_timeout_seconds=connect, total_timeout_seconds=total)


def test_adapter_satisfies_the_port() -> None:
    sender: WebhookSender = _sender(Handler(httpx.Response(200)))

    assert sender is not None


async def test_response_status_and_body_are_returned() -> None:
    handler = Handler(httpx.Response(200, content=b'{"receipt_id": "R-ABC123"}'))

    result = await _sender(handler).send(URL, HEADERS, BODY)

    assert result == SendResult.response(200, b'{"receipt_id": "R-ABC123"}')


async def test_one_post_with_the_body_bytes_and_headers_unchanged() -> None:
    handler = Handler(httpx.Response(200))

    await _sender(handler).send(URL, HEADERS, BODY)

    (request,) = handler.requests
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.content == BODY
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Veranico-Timestamp"] == "1794000000"


async def test_configured_timeouts_are_applied_to_the_request() -> None:
    handler = Handler(httpx.Response(200))

    await _sender(handler, connect=1.5, total=7.0).send(URL, HEADERS, BODY)

    assert handler.requests[0].extensions["timeout"] == {
        "connect": 1.5,
        "read": 7.0,
        "write": 7.0,
        "pool": 7.0,
    }


async def test_total_timeout_bounds_a_response_that_never_goes_idle() -> None:
    # No socket operation times out here: only the deadline over the whole request does.
    handler = Handler(httpx.Response(200), delay=5.0)
    loop = asyncio.get_running_loop()
    started = loop.time()

    result = await _sender(handler, total=0.05).send(URL, HEADERS, BODY)

    assert result == SendResult.failed("timeout")
    assert loop.time() - started < 1.0


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("connect timed out"),
        httpx.ReadTimeout("read timed out"),
        httpx.WriteTimeout("write timed out"),
        httpx.PoolTimeout("pool timed out"),
    ],
)
async def test_client_timeout_maps_to_timeout(error: Exception) -> None:
    result = await _sender(Handler(error)).send(URL, HEADERS, BODY)

    assert result == SendResult.failed("timeout")


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadError("connection reset"),
        httpx.WriteError("broken pipe"),
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
    ],
)
async def test_connection_failure_maps_to_connection_error(error: Exception) -> None:
    result = await _sender(Handler(error)).send(URL, HEADERS, BODY)

    assert result == SendResult.failed("connection_error")


async def test_redirect_is_returned_not_followed_even_if_the_client_follows() -> None:
    handler = Handler(httpx.Response(302, headers={"Location": "http://elsewhere.test/hook"}))

    result = await _sender(handler, follow_redirects=True).send(URL, HEADERS, BODY)

    assert result.status_code == 302
    assert len(handler.requests) == 1


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_failing_status_is_returned_without_a_second_request(status: int) -> None:
    handler = Handler(httpx.Response(status, headers={"Retry-After": "0"}))

    result = await _sender(handler).send(URL, HEADERS, BODY)

    assert result.status_code == status
    assert len(handler.requests) == 1


async def test_failed_request_is_not_repeated() -> None:
    handler = Handler(httpx.ConnectError("connection refused"))

    await _sender(handler).send(URL, HEADERS, BODY)

    assert len(handler.requests) == 1
