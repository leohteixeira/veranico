"""Public surface of `carriers`: delivery facade and the webhook wire contract."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from veranico.modules.quoting.contracts import CarrierCatalog, DeliveryAttempt, SubmissionPayload
from veranico.shared.kernel.ids import EventId


class DeliveryOutcome(BaseModel, frozen=True):
    delivered: bool
    retryable: bool
    attempt: DeliveryAttempt


class CarriersFacade(Protocol):
    def catalog(self) -> CarrierCatalog: ...  # sync
    async def deliver(
        self, event_id: EventId, attempt: int
    ) -> DeliveryOutcome: ...  # one attempt; records it through quoting


class WebhookEnvelope(BaseModel, frozen=True):
    event_id: EventId
    event_type: Literal["quoting.submission_approved"]
    version: Literal[1]
    occurred_at: datetime
    data: SubmissionPayload


class Receipt(BaseModel, frozen=True):
    receipt_id: str  # "R-" + 6
    event_id: EventId
    received_at: datetime
