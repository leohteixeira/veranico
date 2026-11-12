"""Submission, approval and redelivery use cases."""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from veranico.modules.quoting.application.ports import OutboxStore, QuoteRepository
from veranico.modules.quoting.application.quotes import key_id_of, owned
from veranico.modules.quoting.contracts import (
    Actor,
    ApprovalView,
    CarrierCatalog,
    Decision,
    OutboxDispatcher,
    QuoteStatus,
    Submission,
)
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import (
    ForbiddenError,
    InvalidStateError,
    NotFoundError,
    UnknownCarrierError,
)
from veranico.shared.kernel.ids import (
    EventId,
    QuoteId,
    SubmissionId,
    new_event_id,
    new_submission_id,
)
from veranico.shared.kernel.principal import Principal

ApprovalStatus = Literal["pending", "approved", "rejected"]

_logger = logging.getLogger(__name__)

_APPROVAL_STATUS: dict[QuoteStatus, ApprovalStatus] = {
    "pending_approval": "pending",
    "approved": "approved",
    "submitted": "approved",
    "rejected": "rejected",
}


class OutboxEnqueuer:
    """Hands a committed event to the dispatcher and marks its record `enqueued`.

    A failure is logged and swallowed: the event is committed, its record stays `pending`
    and the sweep hands it over later. The dispatcher is idempotent per event id, so an
    event handed over twice (a failure between the two steps) is delivered once.
    """

    def __init__(self, *, outbox: OutboxStore, dispatcher: OutboxDispatcher, clock: Clock) -> None:
        self._outbox = outbox
        self._dispatcher = dispatcher
        self._clock = clock

    async def enqueue(self, event_id: EventId) -> bool:
        try:
            await self._dispatcher.enqueue(event_id)
            await self._outbox.mark_enqueued(event_id, self._clock.now())
        except Exception:
            # The formatter writes the exception type and frames, never its message.
            _logger.warning(
                "outbox event not enqueued; left to the sweep",
                extra={"event_id": event_id},
                exc_info=True,
            )
            return False
        return True


class ApprovalService:
    def __init__(
        self,
        *,
        quotes: QuoteRepository,
        carriers: CarrierCatalog,
        enqueuer: OutboxEnqueuer,
        clock: Clock,
        sweep: Callable[[], Awaitable[int]],
        new_submission: Callable[[], SubmissionId] = new_submission_id,
        new_event: Callable[[], EventId] = new_event_id,
    ) -> None:
        self._quotes = quotes
        self._carriers = carriers
        self._enqueuer = enqueuer
        self._clock = clock
        self._sweep = sweep
        self._new_submission = new_submission
        self._new_event = new_event

    async def request_submission(
        self, principal: Principal, quote_id: QuoteId, carrier_id: str, actor: Actor
    ) -> Submission:
        owned(await self._quotes.get(quote_id), principal)
        submission_id = self._new_submission()
        at = self._clock.now()

        def mutate(quote: Quote) -> Mutation:
            owned(quote, principal)
            requestable = quote.submission is None and quote.status == "draft"
            if requestable and self._carriers.get(carrier_id) is None:
                raise UnknownCarrierError
            return quote.request_submission(
                submission_id=submission_id,
                carrier_id=carrier_id,
                actor=actor,
                at=at,
                key_id=key_id_of(principal),
            )

        submission = (await self._quotes.update(quote_id, mutate)).quote.submission
        assert submission is not None  # request_submission always leaves one
        return submission

    async def list_approvals(
        self, principal: Principal, status: ApprovalStatus | None
    ) -> list[ApprovalView]:
        # Opportunistic recovery (SPEC section 7); the queue is readable even when it fails.
        try:
            await self._sweep()
        except Exception:
            _logger.warning("outbox sweep failed while listing approvals", exc_info=True)
        quotes = await self._quotes.list_for_workspace(principal.workspace_id)
        approvals = [
            self._view(quote)
            for quote in quotes
            if quote.workspace_id == principal.workspace_id and quote.submission is not None
        ]
        return sorted(
            (approval for approval in approvals if status is None or approval.status == status),
            key=lambda approval: approval.requested_at,
            reverse=True,
        )

    async def decide(
        self, principal: Principal, approval_id: SubmissionId, decision: Decision
    ) -> ApprovalView:
        found = await self._find(principal, approval_id)
        _require_browser(principal)
        # Created before the transaction: its function may run more than once.
        event_id = self._new_event()
        at = self._clock.now()

        def mutate(quote: Quote) -> Mutation:
            _require_approval(quote, principal, approval_id)
            _require_browser(principal)
            return quote.decide(decision, event_id=event_id, at=at)

        mutation = await self._quotes.update(found.quote_id, mutate)
        # The decision is committed. A failed enqueue never undoes or fails it.
        for record in mutation.outbox:
            await self._enqueuer.enqueue(record.event_id)
        return self._view(mutation.quote)

    async def redeliver(self, principal: Principal, approval_id: SubmissionId) -> ApprovalView:
        found = await self._find(principal, approval_id)
        if found.current_event_id is None:
            raise InvalidStateError("the submission has no delivery")
        actor: Actor = "human" if principal.kind == "browser" else "api_client"
        at = self._clock.now()

        def mutate(quote: Quote, record: OutboxRecord) -> Mutation:
            _require_approval(quote, principal, approval_id)
            return quote.request_redelivery(record, actor=actor, at=at)

        mutation = await self._quotes.update_for_event(found.current_event_id, mutate)
        for record in mutation.outbox:
            await self._enqueuer.enqueue(record.event_id)
        return self._view(mutation.quote)

    async def _find(self, principal: Principal, approval_id: SubmissionId) -> Quote:
        """The quote of an approval, outside any transaction; `update` checks it again."""
        return owned(await self._quotes.find_by_submission(approval_id), principal)

    def _view(self, quote: Quote) -> ApprovalView:
        submission = quote.submission
        assert submission is not None  # callers pass only quotes with a submission
        carrier = self._carriers.get(submission.carrier_id)
        return ApprovalView(
            approval_id=submission.submission_id,
            quote_id=quote.quote_id,
            carrier_id=submission.carrier_id,
            carrier_name=carrier.name if carrier is not None else submission.carrier_id,
            location_label=quote.location.label,
            limit=quote.cover.limit,
            premium=quote.priced.premium.premium,
            status=_APPROVAL_STATUS[quote.status],
            delivery=submission.delivery,
            requested_at=submission.requested_at,
        )


def _require_browser(principal: Principal) -> None:
    if principal.kind != "browser":
        raise ForbiddenError("only a browser session decides an approval")


def _require_approval(quote: Quote, principal: Principal, approval_id: SubmissionId) -> None:
    """Workspace first, so a foreign approval answers `not_found` before anything else."""
    owned(quote, principal)
    if quote.submission is None or quote.submission.submission_id != approval_id:
        raise NotFoundError
