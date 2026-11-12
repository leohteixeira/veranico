"""The internal deliver route over HTTP, without any other module's implementation.

The application is this module's API-role router with the problem handlers and the
authentication dependencies; `quoting` is `FakeQuotingFacade` and the webhook goes to an
in-memory sender. Nothing here needs an emulator.
"""

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tests.fakes.app import API_PREFIX, build_test_app
from tests.fakes.quoting import FakeQuotingFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.carriers.application.deliver import DeliveryService
from veranico.modules.carriers.application.delivery_call import DeliveryCalls
from veranico.modules.carriers.application.ports import SendResult
from veranico.modules.carriers.domain.directory import CarrierDirectory
from veranico.modules.carriers.http.router import build_router
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId

ATTEMPT_LIMIT = 3
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
UNAVAILABLE = SendResult.response(503, b"")
REJECTED = SendResult.response(400, b"")


class ScriptedSender:
    """In-memory `WebhookSender`: answers from a script, then with a valid receipt."""

    def __init__(self) -> None:
        self._script: list[SendResult] = []
        self.requests: list[bytes] = []

    def script(self, *results: SendResult) -> None:
        self._script = list(results)

    async def send(self, url: str, headers: Mapping[str, str], body: bytes) -> SendResult:
        self.requests.append(body)
        if self._script:
            return self._script.pop(0)
        receipt = {
            "receipt_id": "R-7K2M9X",
            "event_id": json.loads(body)["event_id"],
            "received_at": "2026-11-10T12:00:01Z",
        }
        return SendResult.response(200, json.dumps(receipt).encode())


@dataclass(frozen=True)
class DeliverApi:
    quoting: FakeQuotingFacade
    sender: ScriptedSender
    event_id: EventId
    client: httpx.AsyncClient

    async def deliver(
        self, *, event_id: str | None = None, headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        path = f"{API_PREFIX}/internal/outbox/{event_id or self.event_id}/deliver"
        return await self.client.post(path, headers=dict(headers or {}))

    def abandon_calls(self) -> int:
        return sum(1 for call in self.quoting.calls if call[0] == "record_delivery_abandoned")


ApiFactory = Callable[..., DeliverApi]


@pytest.fixture
async def api_factory() -> AsyncIterator[ApiFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(**delivery: Any) -> DeliverApi:
        settings = settings_for_tests(delivery={"attempt_limit": ATTEMPT_LIMIT, **delivery})
        clock = FixedClock(NOW)
        quoting = FakeQuotingFacade(clock=clock)
        sender = ScriptedSender()
        secret = settings.delivery.webhook_signing_secret
        assert secret is not None
        service = DeliveryService(
            quoting=quoting,
            directory=CarrierDirectory(settings.delivery.carrier_base_url),
            sender=sender,
            clock=clock,
            signing_secret=secret.get_secret_value(),
        )
        calls = DeliveryCalls(
            carriers=service, quoting=quoting, attempt_limit=settings.delivery.attempt_limit
        )
        app = build_test_app([build_router(calls)], settings=settings)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.test"
        )
        clients.append(client)
        return DeliverApi(
            quoting=quoting, sender=sender, event_id=quoting.seed_approved(), client=client
        )

    yield build
    for client in clients:
        await client.aclose()


@pytest.fixture
def api(api_factory: ApiFactory) -> DeliverApi:
    return api_factory()
