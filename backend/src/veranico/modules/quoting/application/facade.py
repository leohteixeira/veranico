"""`QuotingService`: the whole `QuotingFacade`, composed from the three groups of use cases."""

from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.application.approvals import (
    ApprovalService,
    ApprovalStatus,
    OutboxEnqueuer,
)
from veranico.modules.quoting.application.delivery import DeliveryService
from veranico.modules.quoting.application.ports import (
    IdempotencyStore,
    OutboxStore,
    QuoteRepository,
)
from veranico.modules.quoting.application.quotes import QuoteService
from veranico.modules.quoting.contracts import (
    Actor,
    ApprovalView,
    CarrierCatalog,
    CreateQuote,
    Decision,
    DeliveryAttempt,
    OutboxDispatcher,
    QuoteSummary,
    QuoteView,
    Submission,
    SubmissionApproved,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId
from veranico.shared.kernel.principal import Principal


class QuotingService:
    def __init__(
        self,
        *,
        quotes: QuoteRepository,
        idempotency: IdempotencyStore,
        outbox: OutboxStore,
        climate: ClimateFacade,
        pricing: PricingFacade,
        carriers: CarrierCatalog,
        dispatcher: OutboxDispatcher,
        clock: Clock,
        sweep_age_seconds: int,
        retry_window_seconds: int,
    ) -> None:
        enqueuer = OutboxEnqueuer(outbox=outbox, dispatcher=dispatcher, clock=clock)
        self._sweep_age_seconds = sweep_age_seconds
        self._quoting = QuoteService(
            quotes=quotes, idempotency=idempotency, climate=climate, pricing=pricing, clock=clock
        )
        self._delivery = DeliveryService(
            quotes=quotes,
            outbox=outbox,
            enqueuer=enqueuer,
            clock=clock,
            retry_window_seconds=retry_window_seconds,
        )
        self._approvals = ApprovalService(
            quotes=quotes,
            carriers=carriers,
            enqueuer=enqueuer,
            clock=clock,
            sweep=self._opportunistic_sweep,
        )

    async def _opportunistic_sweep(self) -> int:
        return await self._delivery.sweep_outbox(self._sweep_age_seconds)

    async def create_quote(
        self, principal: Principal, command: CreateQuote, idempotency_key: str | None, actor: Actor
    ) -> QuoteView:
        return await self._quoting.create_quote(principal, command, idempotency_key, actor)

    async def get_quote(self, principal: Principal, quote_id: QuoteId) -> QuoteView:
        return await self._quoting.get_quote(principal, quote_id)

    async def list_quotes(self, principal: Principal) -> list[QuoteSummary]:
        return await self._quoting.list_quotes(principal)

    async def request_submission(
        self, principal: Principal, quote_id: QuoteId, carrier_id: str, actor: Actor
    ) -> Submission:
        return await self._approvals.request_submission(principal, quote_id, carrier_id, actor)

    async def list_approvals(
        self, principal: Principal, status: ApprovalStatus | None
    ) -> list[ApprovalView]:
        return await self._approvals.list_approvals(principal, status)

    async def decide(
        self, principal: Principal, approval_id: SubmissionId, decision: Decision
    ) -> ApprovalView:
        return await self._approvals.decide(principal, approval_id, decision)

    async def redeliver(self, principal: Principal, approval_id: SubmissionId) -> ApprovalView:
        return await self._approvals.redeliver(principal, approval_id)

    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None:
        await self._quoting.append_audit(principal, quote_id, actor, action)

    async def load_event(self, event_id: EventId) -> SubmissionApproved:
        return await self._delivery.load_event(event_id)

    async def record_delivery_attempt(self, attempt: DeliveryAttempt) -> None:
        await self._delivery.record_delivery_attempt(attempt)

    async def record_delivery_abandoned(self, event_id: EventId) -> None:
        await self._delivery.record_delivery_abandoned(event_id)

    async def sweep_outbox(self, older_than_seconds: int) -> int:
        return await self._delivery.sweep_outbox(older_than_seconds)
