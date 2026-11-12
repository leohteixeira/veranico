import asyncio
import re
from datetime import datetime, timedelta

import pytest

from tests.integration.carriers.conftest import (
    NOW,
    Carrier,
    CarrierFactory,
    envelope_body,
    signed_headers,
)
from veranico.modules.carriers.contracts import Receipt
from veranico.modules.carriers.domain.signing import SIGNATURE_HEADER
from veranico.shared.infrastructure.settings import DeliverySettings

pytestmark = [pytest.mark.integration, pytest.mark.req("R-11.4-1")]

RECEIPT_ID = re.compile(r"\AR-[0-9A-Z]{6}\Z")


@pytest.mark.req("R-7-7")
async def test_valid_request_answers_200_with_a_receipt_of_the_event(carrier: Carrier) -> None:
    event_id = carrier.new_event()

    response = await carrier.submit(event_id)

    assert response.status_code == 200
    receipt = Receipt.model_validate(response.json())
    assert receipt.event_id == event_id
    assert RECEIPT_ID.fullmatch(receipt.receipt_id)
    assert receipt.received_at == NOW


@pytest.mark.req("R-7-7")
async def test_tampered_body_answers_401_and_stores_nothing(carrier: Carrier) -> None:
    event_id = carrier.new_event()
    body = envelope_body(event_id)
    headers = signed_headers(body, carrier.clock.now())

    response = await carrier.post(body.replace(b'"BRL"', b'"USD"'), headers)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_signature"
    assert await carrier.document(event_id) is None


@pytest.mark.req("R-7-7")
async def test_missing_signature_answers_401(carrier: Carrier) -> None:
    event_id = carrier.new_event()
    body = envelope_body(event_id)
    headers = signed_headers(body, carrier.clock.now())
    del headers[SIGNATURE_HEADER]

    response = await carrier.post(body, headers)

    assert response.status_code == 401
    assert await carrier.document(event_id) is None


@pytest.mark.req("R-7-8")
async def test_valid_signature_301_seconds_old_answers_400(carrier: Carrier) -> None:
    event_id = carrier.new_event()
    body = envelope_body(event_id)
    headers = signed_headers(body, carrier.clock.now() - timedelta(seconds=301))

    response = await carrier.post(body, headers)

    assert response.status_code == 400
    assert response.json()["code"] == "stale_timestamp"
    assert await carrier.document(event_id) is None


@pytest.mark.req("R-7-8")
async def test_valid_signature_300_seconds_old_is_accepted(carrier: Carrier) -> None:
    event_id = carrier.new_event()
    body = envelope_body(event_id)
    headers = signed_headers(body, carrier.clock.now() - timedelta(seconds=300))

    response = await carrier.post(body, headers)

    assert response.status_code == 200


@pytest.mark.req("R-7-7")
@pytest.mark.req("R-7-8")
async def test_unsigned_request_with_a_stale_timestamp_answers_401_not_400(
    carrier: Carrier,
) -> None:
    event_id = carrier.new_event()
    body = envelope_body(event_id)
    stale = carrier.clock.now() - timedelta(seconds=301)
    headers = signed_headers(body, stale, secret="not-the-shared-secret")

    response = await carrier.post(body, headers)

    assert response.status_code == 401


@pytest.mark.req("R-7-9")
async def test_replayed_event_returns_the_original_receipt(carrier: Carrier) -> None:
    event_id = carrier.new_event()
    first = await carrier.submit(event_id)
    carrier.clock.advance(timedelta(minutes=7))  # a fresh signature, a later time

    second = await carrier.submit(event_id)

    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.json()["received_at"] == first.json()["received_at"]
    document = await carrier.document(event_id)
    assert document is not None
    assert document["receipt_id"] == first.json()["receipt_id"]
    assert document["received_at"] == NOW


@pytest.mark.req("R-7-9")
async def test_stored_receipt_expires_14_days_after_it_was_received(carrier: Carrier) -> None:
    event_id = carrier.new_event()

    await carrier.submit(event_id)

    document = await carrier.document(event_id)
    assert document is not None
    assert document["status"] == "received"
    assert document["event_id"] == event_id
    # A Firestore timestamp (read back as a datetime): the type a TTL policy needs.
    assert isinstance(document["expires_at"], datetime)
    assert document["expires_at"] == document["received_at"] + timedelta(days=14)
    assert document["expires_at"] == NOW + timedelta(days=14)


@pytest.mark.req("R-7-9")
async def test_ten_identical_requests_started_together_return_one_receipt(
    carrier: Carrier,
) -> None:
    event_id = carrier.new_event()

    responses = await asyncio.gather(*(carrier.submit(event_id) for _ in range(10)))

    assert [response.status_code for response in responses] == [200] * 10
    assert len({response.json()["receipt_id"] for response in responses}) == 1
    document = await carrier.document(event_id)
    assert document is not None
    assert document["receipt_id"] == responses[0].json()["receipt_id"]


@pytest.mark.req("R-7-10")
async def test_with_the_switch_on_the_first_attempt_of_each_event_answers_503(
    carrier_factory: CarrierFactory,
) -> None:
    carrier = carrier_factory(fail_first_attempt=True)
    event_id = carrier.new_event()

    first = await carrier.submit(event_id)

    assert first.status_code == 503
    assert first.json()["code"] == "carrier_unavailable"
    deferred = await carrier.document(event_id)
    assert deferred is not None
    assert deferred["status"] == "deferred"
    assert "receipt_id" not in deferred
    assert isinstance(deferred["expires_at"], datetime)
    assert deferred["expires_at"] == NOW + timedelta(days=14)

    carrier.clock.advance(timedelta(seconds=2))
    second = await carrier.submit(event_id)
    third = await carrier.submit(event_id)

    assert second.status_code == 200
    assert third.status_code == 200
    assert third.json() == second.json()
    received = await carrier.document(event_id)
    assert received is not None
    assert received["status"] == "received"
    assert received["receipt_id"] == second.json()["receipt_id"]
    assert received["expires_at"] == received["received_at"] + timedelta(days=14)

    another = carrier.new_event()
    assert (await carrier.submit(another)).status_code == 503


@pytest.mark.req("R-7-10")
async def test_with_the_switch_on_concurrent_first_attempts_defer_once_and_share_a_receipt(
    carrier_factory: CarrierFactory,
) -> None:
    carrier = carrier_factory(fail_first_attempt=True)
    event_id = carrier.new_event()

    responses = await asyncio.gather(*(carrier.submit(event_id) for _ in range(5)))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 200, 200, 200, 503]
    receipts = {r.json()["receipt_id"] for r in responses if r.status_code == 200}
    assert len(receipts) == 1


@pytest.mark.req("R-7-10")
def test_the_switch_is_off_in_default_settings() -> None:
    assert DeliverySettings().carrier_fail_first_attempt is False
