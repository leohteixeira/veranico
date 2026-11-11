import json
import logging
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.fakes.quoting import FakeQuotingFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.carriers.application.deliver import DeliveryService
from veranico.modules.carriers.application.ports import SendResult
from veranico.modules.carriers.contracts import CarriersFacade, Receipt
from veranico.modules.carriers.domain.directory import CARRIERS, CarrierDirectory
from veranico.modules.carriers.domain.signing import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    Verification,
    verify,
)
from veranico.shared.infrastructure import telemetry
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId

SECRET = "unit-test-signing-key"
BASE_URL = "http://carrier.test"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
RECEIVED_AT = "2026-11-10T12:00:01Z"


class RecordingSender:
    """In-memory `WebhookSender`: answers from a script and keeps what it was given."""

    def __init__(self, *results: SendResult) -> None:
        self._results = list(results)
        self.requests: list[tuple[str, dict[str, str], bytes]] = []

    def then(self, result: SendResult) -> None:
        self._results.append(result)

    async def send(self, url: str, headers: Mapping[str, str], body: bytes) -> SendResult:
        self.requests.append((url, dict(headers), body))
        return self._results.pop(0)


def _receipt(event_id: str, receipt_id: str = "R-7K2M9X") -> bytes:
    receipt = {"receipt_id": receipt_id, "event_id": event_id, "received_at": RECEIVED_AT}
    return json.dumps(receipt).encode()


class Scenario:
    def __init__(self, *results: SendResult, carrier_id: str = "carrier-1") -> None:
        self.clock = FixedClock(NOW)
        self.quoting = FakeQuotingFacade(clock=self.clock)
        self.event_id = self.quoting.seed_approved(carrier_id=carrier_id)
        self.sender = RecordingSender(*results)
        self.service = DeliveryService(
            quoting=self.quoting,
            directory=CarrierDirectory(BASE_URL),
            sender=self.sender,
            clock=self.clock,
            signing_secret=SECRET,
        )

    def delivered(self, receipt_id: str = "R-7K2M9X") -> "Scenario":
        self.sender.then(SendResult.response(200, _receipt(self.event_id, receipt_id)))
        return self


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    telemetry.configure(settings_for_tests(), "api", exporter=exporter)
    yield exporter
    telemetry.shutdown()


def test_service_satisfies_the_carriers_facade() -> None:
    scenario = Scenario()
    facade: CarriersFacade = scenario.service

    assert [carrier.carrier_id for carrier in facade.catalog().all()] == [
        entry.carrier_id for entry in CARRIERS
    ]


@pytest.mark.req("R-7-3")
async def test_envelope_carries_the_event_and_nothing_else() -> None:
    scenario = Scenario().delivered()
    event = await scenario.quoting.load_event(scenario.event_id)

    await scenario.service.deliver(scenario.event_id, 1)

    url, headers, body = scenario.sender.requests[0]
    assert url == BASE_URL + "/carrier/v1/submissions"
    assert headers["Content-Type"] == "application/json"
    sent = json.loads(body)
    assert set(sent) == {"event_id", "event_type", "version", "occurred_at", "data"}
    assert sent["event_id"] == event.event_id
    assert sent["event_type"] == "quoting.submission_approved"
    assert sent["version"] == 1
    assert datetime.fromisoformat(sent["occurred_at"]) == event.occurred_at
    assert sent["data"] == event.data.model_dump(mode="json")
    assert "workspace_id" not in sent
    assert "carrier_id" not in sent


@pytest.mark.req("R-7-3")
async def test_money_and_rate_are_forwarded_as_stored() -> None:
    scenario = Scenario().delivered()
    event = await scenario.quoting.load_event(scenario.event_id)

    await scenario.service.deliver(scenario.event_id, 1)

    sent = json.loads(scenario.sender.requests[0][2])
    assert sent["data"]["premium"] == {
        "amount_cents": event.data.premium.amount_cents,
        "currency": "BRL",
    }
    assert sent["data"]["rate_on_line"] == event.data.rate_on_line


@pytest.mark.req("R-7-1")
async def test_sent_bytes_verify_under_the_secret_with_the_timestamp_header() -> None:
    scenario = Scenario().delivered()

    await scenario.service.deliver(scenario.event_id, 1)

    _, headers, body = scenario.sender.requests[0]
    assert headers[TIMESTAMP_HEADER] == str(int(NOW.timestamp()))
    outcome = verify(SECRET, headers[TIMESTAMP_HEADER], headers[SIGNATURE_HEADER], body, NOW, 300)
    assert outcome is Verification.OK


@pytest.mark.req("R-7-3")
@pytest.mark.req("R-7-4")
async def test_valid_receipt_is_delivered_and_recorded() -> None:
    scenario = Scenario().delivered("R-ABC123")

    outcome = await scenario.service.deliver(scenario.event_id, 1)

    assert outcome.delivered is True
    assert outcome.retryable is False
    assert outcome.attempt.event_id == scenario.event_id
    assert outcome.attempt.attempt == 1
    assert outcome.attempt.status_code == 200
    assert outcome.attempt.error_code is None
    assert outcome.attempt.receipt_id == "R-ABC123"
    assert outcome.attempt.duration_ms >= 0
    assert scenario.quoting.delivery_attempts(scenario.event_id) == [outcome.attempt]


@pytest.mark.req("R-7-3")
@pytest.mark.req("R-7-4")
@pytest.mark.parametrize(
    ("result", "status_code", "error_code", "retryable"),
    [
        (SendResult.response(503, b""), 503, "http_error", True),
        (SendResult.response(500, b"oops"), 500, "http_error", True),
        (SendResult.failed("timeout"), None, "timeout", True),
        (SendResult.failed("connection_error"), None, "connection_error", True),
        (SendResult.response(400, b""), 400, "http_error", False),
        (SendResult.response(401, b""), 401, "http_error", False),
        (SendResult.response(302, b""), 302, "http_error", False),
        (SendResult.response(200, b"not json"), 200, "invalid_receipt", True),
        (SendResult.response(200, b""), 200, "invalid_receipt", True),
        (SendResult.response(200, b'{"receipt_id":"R-ABC123"}'), 200, "invalid_receipt", True),
        (SendResult.response(200, _receipt("another-event")), 200, "invalid_receipt", True),
    ],
)
async def test_failure_is_classified_and_recorded(
    result: SendResult, status_code: int | None, error_code: str, retryable: bool
) -> None:
    scenario = Scenario(result)

    outcome = await scenario.service.deliver(scenario.event_id, 3)

    assert outcome.delivered is False
    assert outcome.retryable is retryable
    assert outcome.attempt.attempt == 3
    assert outcome.attempt.status_code == status_code
    assert outcome.attempt.error_code == error_code
    assert outcome.attempt.receipt_id is None
    assert outcome.attempt.duration_ms >= 0
    assert scenario.quoting.delivery_attempts(scenario.event_id) == [outcome.attempt]
    assert len(scenario.sender.requests) == 1


@pytest.mark.req("R-7-3")
async def test_unknown_carrier_is_not_retryable_and_sends_nothing() -> None:
    scenario = Scenario(carrier_id="carrier-gone")

    outcome = await scenario.service.deliver(scenario.event_id, 2)

    assert outcome.delivered is False
    assert outcome.retryable is False
    assert outcome.attempt.error_code == "unknown_carrier"
    assert outcome.attempt.status_code is None
    assert outcome.attempt.attempt == 2
    assert scenario.sender.requests == []
    assert scenario.quoting.delivery_attempts(scenario.event_id) == [outcome.attempt]


async def test_unknown_event_propagates_not_found_and_sends_nothing() -> None:
    scenario = Scenario()

    with pytest.raises(NotFoundError):
        await scenario.service.deliver(EventId("no-such-event"), 1)

    assert scenario.sender.requests == []


@pytest.mark.req("R-7-4")
async def test_every_outcome_records_exactly_one_attempt() -> None:
    scenario = Scenario(SendResult.response(503, b"")).delivered()

    await scenario.service.deliver(scenario.event_id, 1)
    await scenario.service.deliver(scenario.event_id, 2)

    recorded = [call for call in scenario.quoting.calls if call[0] == "record_delivery_attempt"]
    assert len(recorded) == 2
    assert [a.attempt for a in scenario.quoting.delivery_attempts(scenario.event_id)] == [1, 2]
    assert len(scenario.sender.requests) == 2


async def test_span_carries_identifiers_and_the_result(spans: InMemorySpanExporter) -> None:
    scenario = Scenario(SendResult.response(503, b"")).delivered()

    await scenario.service.deliver(scenario.event_id, 1)
    await scenario.service.deliver(scenario.event_id, 2)

    failed, delivered = spans.get_finished_spans()
    assert failed.name == delivered.name == telemetry.SPAN_OUTBOX_DELIVER
    assert dict(failed.attributes or {}) == {
        telemetry.ATTR_OUTBOX_EVENT_ID: scenario.event_id,
        telemetry.ATTR_OUTBOX_ATTEMPT: 1,
        telemetry.ATTR_OUTBOX_STATUS_CODE: 503,
        telemetry.ATTR_OUTBOX_ERROR_CODE: "http_error",
        telemetry.ATTR_OUTBOX_DELIVERED: False,
    }
    assert dict(delivered.attributes or {}) == {
        telemetry.ATTR_OUTBOX_EVENT_ID: scenario.event_id,
        telemetry.ATTR_OUTBOX_ATTEMPT: 2,
        telemetry.ATTR_OUTBOX_STATUS_CODE: 200,
        telemetry.ATTR_OUTBOX_DELIVERED: True,
    }


async def test_log_line_holds_no_secret_signature_or_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scenario = Scenario(SendResult.response(503, b"carrier said no"))

    with caplog.at_level(logging.INFO):
        await scenario.service.deliver(scenario.event_id, 1)

    _, headers, body = scenario.sender.requests[0]
    (record,) = [r for r in caplog.records if r.name.startswith("veranico.modules.carriers")]
    logged = json.dumps({k: repr(v) for k, v in vars(record).items()}) + record.getMessage()
    assert SECRET not in logged
    assert headers[SIGNATURE_HEADER] not in logged
    assert "amount_cents" not in logged
    assert "carrier said no" not in logged
    assert body.decode() not in logged
    assert vars(record)["event_id"] == scenario.event_id
    assert vars(record)["attempt"] == 1
    assert vars(record)["status_code"] == 503
    assert vars(record)["error_code"] == "http_error"


def test_receipt_model_is_the_wire_contract() -> None:
    receipt = Receipt.model_validate_json(_receipt("e-1"))

    assert receipt.event_id == "e-1"
