"""The mock carrier's route with an in-memory receipt store: what the HTTP layer decides
(signature before parsing, validation after it, the wire statuses). The same route on the
Firestore emulator is `tests/integration/carriers/test_receipts.py`.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import pytest

from tests.fakes.settings import settings_for_tests
from tests.integration.carriers.conftest import (
    NOW,
    SECRET,
    SUBMISSIONS_PATH,
    carrier_app,
    envelope_body,
    signed_headers,
)
from veranico.modules.carriers.application.receive import Receiver, StoredSubmission
from veranico.modules.carriers.contracts import Receipt
from veranico.modules.carriers.domain.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER
from veranico.modules.carriers.http.carrier_router import build_carrier_router
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.ids import EventId

pytestmark = pytest.mark.req("R-11.4-1")

EVENT_ID = "0190a8e0-0000-7000-8000-000000000001"


class MemoryReceiptStore:
    """In-memory `ReceiptStore`: the version token counts the writes of a document."""

    def __init__(self) -> None:
        self.documents: dict[str, tuple[Receipt | None, int]] = {}

    async def get(self, event_id: EventId) -> StoredSubmission | None:
        if event_id not in self.documents:
            return None
        receipt, version = self.documents[event_id]
        return StoredSubmission(receipt=receipt, version=version)

    async def create_deferred(self, event_id: EventId, at: datetime, expires_at: datetime) -> bool:
        if event_id in self.documents:
            return False
        self.documents[event_id] = (None, 1)
        return True

    async def create_receipt(self, receipt: Receipt, expires_at: datetime) -> bool:
        if receipt.event_id in self.documents:
            return False
        self.documents[receipt.event_id] = (receipt, 1)
        return True

    async def promote(
        self, deferred: StoredSubmission, receipt: Receipt, expires_at: datetime
    ) -> bool:
        _, version = self.documents[receipt.event_id]
        if version != deferred.version:
            return False
        self.documents[receipt.event_id] = (receipt, version + 1)
        return True


@dataclass(frozen=True)
class CarrierApi:
    client: httpx.AsyncClient
    store: MemoryReceiptStore
    clock: FixedClock

    async def post(self, body: bytes, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(SUBMISSIONS_PATH, content=body, headers=headers)

    def signed(self, body: bytes) -> dict[str, str]:
        return signed_headers(body, self.clock.now())


@pytest.fixture
async def carrier() -> AsyncIterator[CarrierApi]:
    settings = settings_for_tests("carrier", delivery={"webhook_signing_secret": SECRET})
    assert settings.delivery.carrier_fail_first_attempt is False
    store = MemoryReceiptStore()
    clock = FixedClock(NOW)
    receiver = Receiver(
        store=store,
        clock=clock,
        signing_secret=SECRET,
        tolerance_seconds=settings.delivery.timestamp_tolerance_seconds,
        fail_first_attempt=settings.delivery.carrier_fail_first_attempt,
    )
    app = carrier_app(build_carrier_router(receiver))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://carrier.test"
    ) as client:
        yield CarrierApi(client=client, store=store, clock=clock)


@pytest.mark.req("R-7-7")
async def test_signed_envelope_answers_200_with_a_receipt(carrier: CarrierApi) -> None:
    body = envelope_body(EVENT_ID)

    response = await carrier.post(body, carrier.signed(body))

    assert response.status_code == 200
    assert set(response.json()) == {"receipt_id", "event_id", "received_at"}
    assert response.json()["event_id"] == EVENT_ID


@pytest.mark.req("R-7-7")
async def test_signature_is_checked_over_the_received_bytes_not_a_reencoding(
    carrier: CarrierApi,
) -> None:
    # The same JSON value with other whitespace is another byte string: its signature differs.
    body = envelope_body(EVENT_ID)
    respaced = json.dumps(json.loads(body), indent=2).encode()

    rejected = await carrier.post(respaced, carrier.signed(body))
    accepted = await carrier.post(respaced, carrier.signed(respaced))

    assert rejected.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.req("R-7-7")
@pytest.mark.parametrize("body", [b"not json at all", b"", b'{"event_id": "only"}'])
async def test_unsigned_request_answers_401_whatever_its_body(
    carrier: CarrierApi, body: bytes
) -> None:
    response = await carrier.post(body, {"Content-Type": "application/json"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_signature"
    assert response.headers["content-type"] == "application/problem+json"
    assert carrier.store.documents == {}


@pytest.mark.req("R-7-7")
@pytest.mark.parametrize("header", [SIGNATURE_HEADER, TIMESTAMP_HEADER])
async def test_missing_header_answers_401(carrier: CarrierApi, header: str) -> None:
    body = envelope_body(EVENT_ID)
    headers = carrier.signed(body)
    del headers[header]

    response = await carrier.post(body, headers)

    assert response.status_code == 401


@pytest.mark.req("R-7-8")
async def test_stale_signed_request_answers_400(carrier: CarrierApi) -> None:
    body = envelope_body(EVENT_ID)
    headers = signed_headers(body, carrier.clock.now() - timedelta(seconds=301))

    response = await carrier.post(body, headers)

    assert response.status_code == 400
    assert response.json()["code"] == "stale_timestamp"
    assert carrier.store.documents == {}


@pytest.mark.parametrize(
    "body",
    [
        b"signed, but not json",
        b'{"event_id": "e-1"}',
        json.dumps({**json.loads(envelope_body(EVENT_ID)), "version": 2}).encode(),
        json.dumps({**json.loads(envelope_body(EVENT_ID)), "event_id": "a/b"}).encode(),
    ],
)
async def test_signed_body_that_is_not_an_envelope_answers_invalid_arguments(
    carrier: CarrierApi, body: bytes
) -> None:
    response = await carrier.post(body, carrier.signed(body))

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_arguments"
    assert carrier.store.documents == {}


@pytest.mark.req("R-7-9")
async def test_replay_answers_the_original_receipt(carrier: CarrierApi) -> None:
    body = envelope_body(EVENT_ID)
    first = await carrier.post(body, carrier.signed(body))
    carrier.clock.advance(timedelta(hours=1))

    second = await carrier.post(body, carrier.signed(body))

    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(carrier.store.documents) == 1


def test_problem_statuses_of_the_carrier_follow_the_wire_contract() -> None:
    from veranico.modules.carriers.application import receive

    assert receive.InvalidSignatureError.status == 401
    assert receive.StaleTimestampError.status == 400
    assert receive.CarrierUnavailableError.status == 503
