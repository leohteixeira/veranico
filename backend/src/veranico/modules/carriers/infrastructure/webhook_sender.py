"""The `WebhookSender` adapter: one POST over `httpx`, bounded in time, never repeated.

httpx (0.28) has per-operation timeouts only (connect, read, write, pool) and no deadline
over a whole request, so a response that keeps trickling would never trip them. The total
timeout is therefore an `asyncio.timeout` around the call; the per-operation values are the
connect timeout and, for the rest, the total.
"""

import asyncio
from collections.abc import Mapping

import httpx

from veranico.modules.carriers.application.ports import SendResult


class HttpxWebhookSender:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        connect_timeout_seconds: float,
        total_timeout_seconds: float,
    ) -> None:
        self._client = client
        self._total = total_timeout_seconds
        self._timeout = httpx.Timeout(total_timeout_seconds, connect=connect_timeout_seconds)

    async def send(self, url: str, headers: Mapping[str, str], body: bytes) -> SendResult:
        try:
            async with asyncio.timeout(self._total):
                response = await self._client.post(
                    url,
                    content=body,
                    headers=dict(headers),
                    timeout=self._timeout,
                    # Set per request: the client is shared and its default may differ.
                    follow_redirects=False,
                )
        except (httpx.TimeoutException, TimeoutError):
            return SendResult.failed("timeout")
        except httpx.TransportError:
            # Refused, reset, closed mid-response or malformed HTTP: no usable response.
            return SendResult.failed("connection_error")
        return SendResult.response(response.status_code, response.content)
