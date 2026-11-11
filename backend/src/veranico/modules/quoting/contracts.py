"""Public surface of `quoting`: quotes, submissions, approvals, audit trail, outbox event."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from veranico.modules.pricing.contracts import CoverDefinition, PricedCover, SimulationOptions
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId, EventId, QuoteId, SubmissionId, WorkspaceId
from veranico.shared.kernel.money import Money, Rate
from veranico.shared.kernel.principal import Principal

QuoteStatus = Literal["draft", "pending_approval", "approved", "rejected", "submitted"]
Actor = Literal["agent", "human", "api_client", "system", "carrier"]


class QuoteLocation(BaseModel, frozen=True):
    label: str
    lat: float
    lon: float
    h3_cell: str
    admin_region: str | None


class AuditEntry(BaseModel, frozen=True):
    at: datetime
    actor: Actor
    action: Coded  # quote_created, term_sheet_rendered, submission_requested, approved, rejected,
    # webhook_attempt, receipt_recorded, delivery_abandoned, redelivery_requested
    note: str | None = None


class DeliveryState(BaseModel, frozen=True):
    status: Literal["not_started", "delivering", "delivered", "abandoned"]
    attempts: int
    receipt_id: str | None
    last_error_code: str | None


class Submission(BaseModel, frozen=True):
    submission_id: SubmissionId
    carrier_id: str
    requested_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    delivery: DeliveryState


class QuoteView(BaseModel, frozen=True):
    quote_id: QuoteId
    workspace_id: WorkspaceId
    created_at: datetime
    status: QuoteStatus
    location: QuoteLocation
    dataset_id: DatasetId
    cover: CoverDefinition
    priced: PricedCover
    submission: Submission | None
    audit: list[AuditEntry]


class QuoteSummary(BaseModel, frozen=True):
    quote_id: QuoteId
    created_at: datetime
    status: QuoteStatus
    location_label: str
    premium: Money


class QuoteLocationInput(BaseModel, frozen=True):
    lat: float
    lon: float
    label: str | None = None  # defaults to the formatted coordinates
    admin_region: str | None = None


class CreateQuote(
    BaseModel, frozen=True
):  # quoting resolves the grid cell and the dataset through climate
    location: QuoteLocationInput
    cover: CoverDefinition
    simulation: SimulationOptions = SimulationOptions()


class ApprovalView(BaseModel, frozen=True):
    approval_id: SubmissionId
    quote_id: QuoteId
    carrier_id: str
    carrier_name: str
    location_label: str
    limit: Money
    premium: Money
    status: Literal["pending", "approved", "rejected"]
    delivery: DeliveryState
    requested_at: datetime


class Decision(BaseModel, frozen=True):
    approve: bool
    note: str | None = None  # at most 500 characters


class CarrierInfo(BaseModel, frozen=True):
    carrier_id: str
    name: str


class SubmissionPayload(BaseModel, frozen=True):
    quote_id: QuoteId
    submission_id: SubmissionId
    location: QuoteLocation
    cover: CoverDefinition
    premium: Money
    rate_on_line: Rate


class SubmissionApproved(BaseModel, frozen=True):  # integration event, written to the outbox
    event_type: Literal["quoting.submission_approved"] = "quoting.submission_approved"
    version: Literal[1] = 1
    event_id: EventId
    occurred_at: datetime
    workspace_id: WorkspaceId
    carrier_id: str
    data: SubmissionPayload


class DeliveryAttempt(BaseModel, frozen=True):
    event_id: EventId
    attempt: int
    status_code: int | None
    error_code: str | None
    duration_ms: int
    receipt_id: str | None


# Ports declared by quoting and implemented elsewhere (wired in bootstrap.py)
class CarrierCatalog(Protocol):
    def get(self, carrier_id: str) -> CarrierInfo | None: ...
    def all(self) -> list[CarrierInfo]: ...


class OutboxDispatcher(Protocol):  # Cloud Tasks adapter or the in-process relay
    async def enqueue(self, event_id: EventId) -> None: ...  # idempotent per event id


class QuotingFacade(Protocol):
    async def create_quote(
        self, principal: Principal, command: CreateQuote, idempotency_key: str | None, actor: Actor
    ) -> QuoteView: ...
    async def get_quote(self, principal: Principal, quote_id: QuoteId) -> QuoteView: ...
    async def list_quotes(self, principal: Principal) -> list[QuoteSummary]: ...
    async def request_submission(
        self, principal: Principal, quote_id: QuoteId, carrier_id: str, actor: Actor
    ) -> Submission: ...
    async def list_approvals(
        self, principal: Principal, status: Literal["pending", "approved", "rejected"] | None
    ) -> list[ApprovalView]: ...
    async def decide(
        self, principal: Principal, approval_id: SubmissionId, decision: Decision
    ) -> ApprovalView: ...  # browser principals only
    async def redeliver(self, principal: Principal, approval_id: SubmissionId) -> ApprovalView: ...
    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None: ...
    # system side, used by carriers and the internal endpoints
    async def load_event(self, event_id: EventId) -> SubmissionApproved: ...
    async def record_delivery_attempt(
        self, attempt: DeliveryAttempt
    ) -> None: ...  # a receipt moves the quote to submitted
    async def record_delivery_abandoned(self, event_id: EventId) -> None: ...
    # enqueues committed, never-enqueued events; abandons deliveries silent past the retry window
    async def sweep_outbox(self, older_than_seconds: int) -> int: ...
