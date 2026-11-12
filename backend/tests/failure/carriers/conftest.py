"""Both roles of `carriers` in one process: the API role's deliver route on one side, the
mock carrier on the other, joined by `httpx.ASGITransport`.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/failure/carriers -m failure -q -k "not proxy"

Each side is built by `module.build` as its role builds it: the API side with
`FakeQuotingFacade` and the real `httpx` sender (its client's transport is the carrier
application), the carrier side without a quoting facade, on the Firestore emulator. Each
side has its own clock and its own settings, so a test can give them different secrets or
times. The emulator is shared: events get fresh ids and only their documents are deleted.
"""

import os
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.app import API_PREFIX, build_test_app
from tests.fakes.quoting import FakeQuotingFacade
from tests.fakes.settings import settings_for_tests
from tests.integration.carriers.conftest import carrier_app
from veranico.modules.carriers import module as carriers_module
from veranico.modules.carriers.http.router import ATTEMPT_BASE_HEADER, RETRY_COUNT_HEADER
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId, WorkspaceId, new_event_id
from veranico.shared.kernel.principal import Principal

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
SECRET = "failure-campaign-signing-key"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
ATTEMPT_LIMIT = 3
COLLECTION = "carriers_receipts"
CARRIER_URL = "http://carrier.test"
WORKSPACE = "ws-1"


class _FreshEventIds(FakeQuotingFacade):
    """The fake numbers its events 1, 2, 3 in every test; the carrier's receipts live on a
    shared emulator and are keyed by event id, so each event here gets a new UUIDv7."""

    def _next_event_id(self) -> EventId:
        return new_event_id()


@dataclass(frozen=True)
class ApiSide:
    client: httpx.AsyncClient

    async def deliver(
        self, event_id: str, *, retry_count: int = 0, base: int | None = None
    ) -> httpx.Response:
        """One call of the queue to the deliver route."""
        headers = {RETRY_COUNT_HEADER: str(retry_count)}
        if base is not None:
            headers[ATTEMPT_BASE_HEADER] = str(base)
        return await self.client.post(
            f"{API_PREFIX}/internal/outbox/{event_id}/deliver", headers=headers
        )


@dataclass
class Stack:
    quoting: FakeQuotingFacade
    carrier_clock: FixedClock
    carrier_http: httpx.AsyncClient  # reaches the carrier application
    firestore: AsyncClient
    event_ids: list[EventId] = field(default_factory=list)
    _clients: list[httpx.AsyncClient] = field(default_factory=list)

    def approved_event(self) -> EventId:
        event_id = self.quoting.seed_approved(workspace_id=WORKSPACE)
        self.event_ids.append(event_id)
        return event_id

    def api(self, *, secret: str = SECRET, clock_behind: timedelta = timedelta(0)) -> ApiSide:
        """An API role that signs with `secret` and whose clock runs `clock_behind` late.
        Every API side of a stack shares the quoting facade and the carrier."""
        settings = settings_for_tests(
            delivery={
                "webhook_signing_secret": secret,
                "carrier_base_url": CARRIER_URL,
                "attempt_limit": ATTEMPT_LIMIT,
            }
        )
        module = carriers_module.build(
            carriers_module.CarriersDeps(
                settings=settings,
                clock=FixedClock(self.carrier_clock.now() - clock_behind),
                firestore=self.firestore,
                http=self.carrier_http,
                quoting=self.quoting,
            )
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=build_test_app(module.routers, settings=settings)),
            base_url="http://api.test",
        )
        self._clients.append(client)
        return ApiSide(client=client)

    async def quote(self, event_id: EventId) -> QuoteView:
        event = await self.quoting.load_event(event_id)
        principal = Principal(workspace_id=WorkspaceId(WORKSPACE), kind="browser")
        return await self.quoting.get_quote(principal, event.data.quote_id)

    async def receipt_document(self, event_id: str) -> dict[str, Any] | None:
        snapshot = await self.firestore.collection(COLLECTION).document(event_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def close(self) -> None:
        for client in [*self._clients, self.carrier_http]:
            await client.aclose()
        for event_id in self.event_ids:
            await self.firestore.collection(COLLECTION).document(event_id).delete()


StackFactory = Callable[..., Stack]


@pytest.fixture
async def firestore() -> AsyncIterator[AsyncClient]:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    client = firestore_client(settings_for_tests("carrier", firestore_emulator_host=FIRESTORE_HOST))
    yield client
    await close_firestore(client)


@pytest.fixture
async def stack_factory(firestore: AsyncClient) -> AsyncIterator[StackFactory]:
    stacks: list[Stack] = []
    unused_http = httpx.AsyncClient()  # the carrier role makes no outbound call

    def build(*, fail_first_attempt: bool = False) -> Stack:
        carrier_clock = FixedClock(NOW)
        carrier = carriers_module.build(
            carriers_module.CarriersDeps(
                settings=settings_for_tests(
                    "carrier",
                    firestore_emulator_host=FIRESTORE_HOST,
                    delivery={
                        "webhook_signing_secret": SECRET,
                        "carrier_fail_first_attempt": fail_first_attempt,
                    },
                ),
                clock=carrier_clock,
                firestore=firestore,
                http=unused_http,
                quoting=None,
            )
        )
        stack = Stack(
            quoting=_FreshEventIds(clock=carrier_clock),
            carrier_clock=carrier_clock,
            carrier_http=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=carrier_app(carrier.carrier_router))
            ),
            firestore=firestore,
        )
        stacks.append(stack)
        return stack

    yield build
    for stack in stacks:
        await stack.close()
    await unused_http.aclose()


@pytest.fixture
def stack(stack_factory: StackFactory) -> Stack:
    """Both roles with one secret, one time and the "fail first attempt" switch off."""
    return stack_factory()
