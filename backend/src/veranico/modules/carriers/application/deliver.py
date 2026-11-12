"""Deliver one webhook attempt: sign, send once, classify, record through `quoting`.

Retrying belongs to the queue (Cloud Tasks, or the relay in development) and to nothing
here: one call of `deliver` makes at most one request. The event id is the idempotency key
that makes the queue's retries safe, because the carrier deduplicates by it.
"""

import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from veranico.modules.carriers.application.ports import SendResult, WebhookSender
from veranico.modules.carriers.contracts import DeliveryOutcome, Receipt, WebhookEnvelope
from veranico.modules.carriers.domain.directory import CarrierDirectory
from veranico.modules.carriers.domain.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from veranico.modules.quoting.contracts import (
    CarrierCatalog,
    DeliveryAttempt,
    QuotingFacade,
    SubmissionApproved,
)
from veranico.shared.infrastructure import telemetry
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.ids import EventId

_logger = logging.getLogger(__name__)

# `DeliveryAttempt.error_code` values. The frontend translates them.
TIMEOUT = "timeout"
CONNECTION_ERROR = "connection_error"
HTTP_ERROR = "http_error"  # the status code says which
INVALID_RECEIPT = "invalid_receipt"
UNKNOWN_CARRIER = "unknown_carrier"


@dataclass(frozen=True, slots=True)
class _Result:
    status_code: int | None
    error_code: str | None
    retryable: bool
    receipt_id: str | None = None


class DeliveryService:
    """Implements `CarriersFacade` on the API role."""

    def __init__(
        self,
        *,
        quoting: QuotingFacade,
        directory: CarrierDirectory,
        sender: WebhookSender,
        clock: Clock,
        signing_secret: str,
    ) -> None:
        self._quoting = quoting
        self._directory = directory
        self._sender = sender
        self._clock = clock
        self._signing_secret = signing_secret

    def catalog(self) -> CarrierCatalog:
        return self._directory

    async def deliver(self, event_id: EventId, attempt: int) -> DeliveryOutcome:
        with telemetry.tracer().start_as_current_span(
            telemetry.SPAN_OUTBOX_DELIVER,
            attributes={
                telemetry.ATTR_OUTBOX_EVENT_ID: event_id,
                telemetry.ATTR_OUTBOX_ATTEMPT: attempt,
            },
        ) as span:
            event = await self._quoting.load_event(event_id)  # not_found propagates
            started = time.perf_counter_ns()
            result = await self._attempt(event)
            duration_ms = (time.perf_counter_ns() - started) // 1_000_000

            delivered = result.receipt_id is not None
            if result.status_code is not None:
                span.set_attribute(telemetry.ATTR_OUTBOX_STATUS_CODE, result.status_code)
            if result.error_code is not None:
                span.set_attribute(telemetry.ATTR_OUTBOX_ERROR_CODE, result.error_code)
            span.set_attribute(telemetry.ATTR_OUTBOX_DELIVERED, delivered)
            # Identifiers and the result only: never the secret, the signature or a body.
            _logger.info(
                "webhook attempt",
                extra={
                    "event_id": event_id,
                    "attempt": attempt,
                    "status_code": result.status_code,
                    "error_code": result.error_code,
                    "duration_ms": duration_ms,
                    "delivered": delivered,
                },
            )

            recorded = DeliveryAttempt(
                event_id=event_id,
                attempt=attempt,
                status_code=result.status_code,
                error_code=result.error_code,
                duration_ms=duration_ms,
                receipt_id=result.receipt_id,
            )
            await self._quoting.record_delivery_attempt(recorded)
            return DeliveryOutcome(
                delivered=delivered, retryable=result.retryable, attempt=recorded
            )

    async def _attempt(self, event: SubmissionApproved) -> _Result:
        url = self._directory.webhook_url(event.carrier_id)
        if url is None:
            return _Result(status_code=None, error_code=UNKNOWN_CARRIER, retryable=False)
        envelope = WebhookEnvelope(
            event_id=event.event_id,
            event_type=event.event_type,
            version=event.version,
            occurred_at=event.occurred_at,
            data=event.data,
        )
        # Serialised once: these exact bytes are signed and sent.
        body = envelope.model_dump_json().encode("utf-8")
        timestamp = int(self._clock.now().timestamp())
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: str(timestamp),
            SIGNATURE_HEADER: sign(self._signing_secret, timestamp, body),
        }
        return _classify(await self._sender.send(url, headers, body), event.event_id)


def _classify(sent: SendResult, event_id: EventId) -> _Result:
    """Contracts section 6: a 5xx, a timeout or a connection error is retryable; a 4xx is
    not. Decided by the plan: a 2xx without a receipt for this event is retryable (a
    transport fault; the carrier deduplicates), and a 3xx is not followed and not retryable.
    """
    if sent.failure is not None or sent.status_code is None:
        return _Result(status_code=None, error_code=sent.failure, retryable=True)
    status = sent.status_code
    if 200 <= status < 300:
        receipt_id = _receipt_id(sent.body, event_id)
        if receipt_id is None:
            return _Result(status_code=status, error_code=INVALID_RECEIPT, retryable=True)
        return _Result(status_code=status, error_code=None, retryable=False, receipt_id=receipt_id)
    return _Result(status_code=status, error_code=HTTP_ERROR, retryable=status >= 500)


def _receipt_id(body: bytes, event_id: EventId) -> str | None:
    try:
        receipt = Receipt.model_validate_json(body)
    except ValidationError:
        return None
    return receipt.receipt_id if receipt.event_id == event_id else None
