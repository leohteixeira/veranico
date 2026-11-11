"""The mock carrier over HTTP on the shared Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/carriers -m integration -q

The application is the carrier-role router of this module, built by `module.build` exactly
as `APP_ROLE=carrier` builds it (no quoting facade), with the problem handlers. The emulator
is shared: every test uses fresh event ids, deletes only the documents of those ids and
never clears anything else. The helpers `envelope_body`, `signed_headers` and `carrier_app`
are also used by `tests/api/carriers/test_carrier_route.py`.
"""

import os
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from google.cloud.firestore import AsyncClient

from tests.fakes import builders
from tests.fakes.settings import settings_for_tests
from veranico.modules.carriers import module as carriers_module
from veranico.modules.carriers.contracts import WebhookEnvelope
from veranico.modules.carriers.domain.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from veranico.modules.quoting.contracts import SubmissionPayload
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.infrastructure.problems import PROBLEM_RESPONSES, install_problem_handlers
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId, SubmissionId, new_event_id

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")
SECRET = "carrier-test-signing-key"
NOW = datetime(2026, 11, 10, 12, 0, 0, 123456, tzinfo=UTC)
SUBMISSIONS_PATH = "/carrier/v1/submissions"
COLLECTION = "carriers_receipts"


def envelope_body(event_id: str) -> bytes:
    """The webhook body the API role would send for this event."""
    view = builders.quote_view()
    envelope = WebhookEnvelope(
        event_id=EventId(event_id),
        event_type="quoting.submission_approved",
        version=1,
        occurred_at=NOW,
        data=SubmissionPayload(
            quote_id=view.quote_id,
            submission_id=SubmissionId("S-000001"),
            location=view.location,
            cover=view.cover,
            premium=view.priced.premium.premium,
            rate_on_line=view.priced.premium.rate_on_line,
        ),
    )
    return envelope.model_dump_json().encode("utf-8")


def signed_headers(body: bytes, at: datetime, *, secret: str = SECRET) -> dict[str, str]:
    timestamp = int(at.timestamp())
    return {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: sign(secret, timestamp, body),
    }


def carrier_app(router: APIRouter) -> FastAPI:
    """The carrier role's application: the router at the root, with the problem handlers."""
    app = FastAPI(responses=PROBLEM_RESPONSES)
    install_problem_handlers(app)
    app.include_router(router)
    return app


@dataclass
class Carrier:
    client: httpx.AsyncClient
    clock: FixedClock
    firestore: AsyncClient
    event_ids: list[EventId] = field(default_factory=list)

    def new_event(self) -> EventId:
        event_id = new_event_id()
        self.event_ids.append(event_id)
        return event_id

    async def submit(self, event_id: str) -> httpx.Response:
        """Send the event, freshly signed at the carrier's current time."""
        body = envelope_body(event_id)
        return await self.post(body, signed_headers(body, self.clock.now()))

    async def post(self, body: bytes, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(SUBMISSIONS_PATH, content=body, headers=headers)

    async def document(self, event_id: str) -> dict[str, Any] | None:
        snapshot = await self.firestore.collection(COLLECTION).document(event_id).get()
        return snapshot.to_dict() if snapshot.exists else None


CarrierFactory = Callable[..., Carrier]


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
async def carrier_factory(firestore: AsyncClient) -> AsyncIterator[CarrierFactory]:
    carriers: list[Carrier] = []
    unused_http = httpx.AsyncClient()  # the carrier role makes no outbound call

    def build(*, fail_first_attempt: bool | None = None) -> Carrier:
        delivery: dict[str, Any] = {"webhook_signing_secret": SECRET}
        if fail_first_attempt is not None:
            delivery["carrier_fail_first_attempt"] = fail_first_attempt
        settings = settings_for_tests(
            "carrier", firestore_emulator_host=FIRESTORE_HOST, delivery=delivery
        )
        clock = FixedClock(NOW)
        module = carriers_module.build(
            carriers_module.CarriersDeps(
                settings=settings, clock=clock, firestore=firestore, http=unused_http, quoting=None
            )
        )
        assert module.routers == ()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=carrier_app(module.carrier_router)),
            base_url="http://carrier.test",
        )
        carrier = Carrier(client=client, clock=clock, firestore=firestore)
        carriers.append(carrier)
        return carrier

    yield build
    for carrier in carriers:
        await carrier.client.aclose()
        for event_id in carrier.event_ids:
            await firestore.collection(COLLECTION).document(event_id).delete()
    await unused_http.aclose()


@pytest.fixture
def carrier(carrier_factory: CarrierFactory) -> Carrier:
    """The mock carrier with default settings: the "fail first attempt" switch is off."""
    return carrier_factory()
