"""Network faults on the webhook path, injected by the fault proxy (SPEC 16.3).

    make test-failure

or, with the `failure` Compose profile and a carrier role running and the variables of
`proxy.py` exported, `uv run pytest tests/failure/carriers/test_proxy_faults.py -m failure`.

The deliver use case runs with the real `httpx` sender pointed at the proxy's listener; a
real carrier role sits behind the proxy. Whatever the fault, one call makes one attempt,
bounded by the webhook timeout and recorded with its duration, and once the fault is gone
the event is delivered with exactly one receipt.
"""

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from google.cloud.firestore import AsyncClient

from tests.failure.carriers.conftest import COLLECTION, _FreshEventIds
from tests.failure.carriers.proxy import SECRET_VARIABLE, FaultProxy, ProxyAddresses
from tests.fakes.quoting import FakeQuotingFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.carriers.application.deliver import DeliveryService
from veranico.modules.carriers.contracts import DeliveryOutcome
from veranico.modules.carriers.domain.directory import CarrierDirectory
from veranico.modules.carriers.infrastructure.webhook_sender import HttpxWebhookSender
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import SystemClock
from veranico.shared.kernel.ids import EventId

pytestmark = [pytest.mark.failure, pytest.mark.req("R-16.3-9"), pytest.mark.req("R-7-3")]

CONNECT_TIMEOUT_SECONDS = 0.5
TOTAL_TIMEOUT_SECONDS = 1.0
# How far past the total timeout a recorded duration may be: scheduling, not waiting.
MARGIN_MS = 500
LATENCY_MS = 3_000  # well above the total timeout


@dataclass
class ProxiedDelivery:
    proxy: FaultProxy
    service: DeliveryService
    quoting: FakeQuotingFacade
    firestore: AsyncClient
    event_id: EventId

    async def stored_receipt(self, *, wait_seconds: float = 0.0) -> dict[str, Any] | None:
        """The carrier's document of the event; optionally wait for the carrier, which
        finishes a request on its own time once the sender has given up on it."""
        document = self.firestore.collection(COLLECTION).document(self.event_id)
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            snapshot = await document.get()
            if snapshot.exists or asyncio.get_running_loop().time() >= deadline:
                return snapshot.to_dict() if snapshot.exists else None
            await asyncio.sleep(0.1)

    async def assert_delivered_with_one_receipt(self, attempt: int) -> str:
        """With the fault gone, the next attempt delivers; the carrier holds one receipt."""
        outcome = await self.service.deliver(self.event_id, attempt)
        assert outcome.delivered is True, outcome
        assert outcome.attempt.status_code == 200
        receipt_id = outcome.attempt.receipt_id
        assert receipt_id is not None
        stored = await self.stored_receipt()
        assert stored is not None
        assert stored["status"] == "received"
        assert stored["receipt_id"] == receipt_id
        recorded = self.quoting.delivery_attempts(self.event_id)
        assert [a.attempt for a in recorded] == list(range(1, attempt + 1))
        return receipt_id

    def assert_recorded_failure(self, outcome: DeliveryOutcome) -> None:
        """A failed attempt is retryable, recorded once and bounded by the timeout."""
        assert outcome.delivered is False
        assert outcome.retryable is True
        assert outcome.attempt.receipt_id is None
        assert self.quoting.delivery_attempts(self.event_id)[-1] == outcome.attempt
        assert 0 <= outcome.attempt.duration_ms <= TOTAL_TIMEOUT_SECONDS * 1000 + MARGIN_MS


@pytest.fixture
async def delivery() -> AsyncIterator[ProxiedDelivery]:
    addresses = ProxyAddresses.from_environment()
    if addresses is None:
        pytest.skip("the fault proxy variables are not set: run `make test-failure`")
    secret = os.environ.get(SECRET_VARIABLE)
    firestore_host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    assert secret, f"{SECRET_VARIABLE} must be the secret the carrier role was started with"
    assert firestore_host, "FIRESTORE_EMULATOR_HOST must name the emulator the carrier role uses"
    host, _, port = firestore_host.partition(":")
    socket.create_connection((host, int(port)), timeout=2).close()

    proxy = FaultProxy(addresses)
    await proxy.create()  # fails here when the control API does not answer
    # The same settings source as the carrier role, so the same Firestore project.
    firestore = firestore_client(
        settings_for_tests("carrier", firestore_emulator_host=firestore_host)
    )
    sender_client = httpx.AsyncClient()
    quoting = _FreshEventIds()
    event_id = quoting.seed_approved()
    service = DeliveryService(
        quoting=quoting,
        directory=CarrierDirectory(addresses.listener_url),
        sender=HttpxWebhookSender(
            sender_client,
            connect_timeout_seconds=CONNECT_TIMEOUT_SECONDS,
            total_timeout_seconds=TOTAL_TIMEOUT_SECONDS,
        ),
        clock=SystemClock(),
        signing_secret=secret,
    )
    try:
        yield ProxiedDelivery(
            proxy=proxy, service=service, quoting=quoting, firestore=firestore, event_id=event_id
        )
    finally:
        await sender_client.aclose()
        await proxy.delete()
        await firestore.collection(COLLECTION).document(event_id).delete()
        await close_firestore(firestore)


async def test_without_a_fault_the_event_is_delivered_through_the_proxy(
    delivery: ProxiedDelivery,
) -> None:
    await delivery.assert_delivered_with_one_receipt(attempt=1)


async def test_latency_above_the_timeout_on_the_response_path_is_a_timeout(
    delivery: ProxiedDelivery,
) -> None:
    toxic = await delivery.proxy.add_toxic("latency", "downstream", latency=LATENCY_MS, jitter=0)

    outcome = await delivery.service.deliver(delivery.event_id, 1)

    delivery.assert_recorded_failure(outcome)
    assert outcome.attempt.error_code == "timeout"
    assert outcome.attempt.status_code is None
    assert outcome.attempt.duration_ms >= TOTAL_TIMEOUT_SECONDS * 1000 - 100
    # The request itself arrived: the carrier stored the receipt the sender never saw.
    stored = await delivery.stored_receipt(wait_seconds=5.0)
    assert stored is not None
    assert stored["status"] == "received"

    await delivery.proxy.remove_toxic(toxic)
    receipt_id = await delivery.assert_delivered_with_one_receipt(attempt=2)

    assert receipt_id == stored["receipt_id"]  # the original receipt, not a second one


async def test_connection_reset_is_a_connection_error(delivery: ProxiedDelivery) -> None:
    toxic = await delivery.proxy.add_toxic("reset_peer", "upstream", timeout=0)

    outcome = await delivery.service.deliver(delivery.event_id, 1)

    delivery.assert_recorded_failure(outcome)
    assert outcome.attempt.error_code == "connection_error"
    assert outcome.attempt.status_code is None

    await delivery.proxy.remove_toxic(toxic)
    await delivery.assert_delivered_with_one_receipt(attempt=2)


async def test_disabled_proxy_is_a_connection_error(delivery: ProxiedDelivery) -> None:
    await delivery.proxy.set_enabled(False)

    outcome = await delivery.service.deliver(delivery.event_id, 1)

    delivery.assert_recorded_failure(outcome)
    assert outcome.attempt.error_code == "connection_error"
    assert outcome.attempt.status_code is None
    assert await delivery.stored_receipt() is None

    await delivery.proxy.set_enabled(True)
    await delivery.assert_delivered_with_one_receipt(attempt=2)


async def test_truncated_response_is_a_retryable_failure(delivery: ProxiedDelivery) -> None:
    # The connection closes after 20 bytes of the response: not even the status line's
    # headers are complete, so there is no usable response.
    toxic = await delivery.proxy.add_toxic("limit_data", "downstream", bytes=20)

    outcome = await delivery.service.deliver(delivery.event_id, 1)

    delivery.assert_recorded_failure(outcome)
    assert outcome.attempt.error_code in {"connection_error", "invalid_receipt"}
    stored = await delivery.stored_receipt(wait_seconds=5.0)
    assert stored is not None  # the carrier answered; only the answer was cut

    await delivery.proxy.remove_toxic(toxic)
    receipt_id = await delivery.assert_delivered_with_one_receipt(attempt=2)

    assert receipt_id == stored["receipt_id"]
