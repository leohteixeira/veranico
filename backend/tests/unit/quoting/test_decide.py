from collections.abc import Callable
from datetime import timedelta

import pytest

from tests.unit.quoting.memory import MemoryQuoteRepository
from tests.unit.quoting.world import API_KEY, BROWSER, NOW, STRANGER, STRANGER_KEY, World
from veranico.modules.quoting.application.approvals import ApprovalService
from veranico.modules.quoting.contracts import Decision, DeliveryState
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.errors import (
    ForbiddenError,
    InvalidArgumentsError,
    InvalidStateError,
    NotFoundError,
)
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId

EVENT_1 = EventId("0190a8e0-0000-7000-8000-000000000001")


@pytest.fixture
def world() -> World:
    return World()


@pytest.mark.req("R-6-7")
@pytest.mark.req("R-6-2")
async def test_an_approval_stores_state_note_audit_and_outbox_then_enqueues_once(
    world: World,
) -> None:
    submission = await world.pending()
    world.clock.advance(timedelta(minutes=10))
    decided_at = NOW + timedelta(minutes=10)

    approval = await world.approvals.decide(
        BROWSER, submission.submission_id, Decision(approve=True, note="go ahead")
    )

    view = await world.view(approval.quote_id)
    assert view.status == "approved"
    assert view.submission is not None
    assert (view.submission.decided_at, view.submission.decision_note) == (decided_at, "go ahead")
    entry = view.audit[-1]
    assert (entry.at, entry.actor, entry.note) == (decided_at, "human", "go ahead")
    assert entry.action.code == "audit.approved"
    assert [e.action.code for e in view.audit].count("audit.approved") == 1
    record = world.record_of(approval.quote_id)
    assert list(world.outbox.records) == [EVENT_1]
    assert record.event.data.submission_id == submission.submission_id
    assert record.event.occurred_at == decided_at
    assert world.dispatcher.enqueued == [EVENT_1]
    assert (record.status, record.enqueued_at) == ("enqueued", decided_at)
    assert (approval.status, approval.approval_id) == ("approved", submission.submission_id)
    assert approval.delivery == DeliveryState(
        status="delivering", attempts=0, receipt_id=None, last_error_code=None
    )


@pytest.mark.req("R-6-7")
async def test_a_rejection_stores_no_outbox_record_and_never_calls_the_dispatcher(
    world: World,
) -> None:
    submission = await world.pending()

    approval = await world.approvals.decide(
        BROWSER, submission.submission_id, Decision(approve=False, note="too risky")
    )

    view = await world.view(approval.quote_id)
    assert view.status == "rejected"
    assert view.submission is not None
    assert view.submission.decision_note == "too risky"
    assert (view.audit[-1].actor, view.audit[-1].action.code) == ("human", "audit.rejected")
    assert view.audit[-1].note == "too risky"
    assert world.outbox.records == {}
    assert world.dispatcher.enqueued == []
    assert (approval.status, approval.delivery.status) == ("rejected", "not_started")


@pytest.mark.req("R-6-7")
@pytest.mark.req("R-7-5")
async def test_a_dispatcher_that_raises_leaves_the_decision_approved_and_the_record_pending(
    world: World,
) -> None:
    submission = await world.pending()
    world.dispatcher.failure = RuntimeError("queue unavailable")

    approval = await world.approvals.decide(
        BROWSER, submission.submission_id, Decision(approve=True)
    )

    assert approval.status == "approved"
    assert approval.delivery.status == "delivering"
    assert (await world.view(approval.quote_id)).status == "approved"
    record = world.record_of(approval.quote_id)
    assert (record.status, record.enqueued_at) == ("pending", None)
    assert world.dispatcher.enqueued == []


@pytest.mark.req("R-6-3")
async def test_an_api_key_of_the_same_workspace_is_forbidden_and_changes_nothing(
    world: World,
) -> None:
    submission = await world.pending()

    for approve in (True, False):
        with pytest.raises(ForbiddenError):
            await world.approvals.decide(
                API_KEY, submission.submission_id, Decision(approve=approve)
            )

    quote_id = next(iter(world.quotes.quotes))
    assert (await world.view(quote_id)).status == "pending_approval"
    assert world.outbox.records == {}
    assert world.dispatcher.enqueued == []


@pytest.mark.req("R-6-3")
@pytest.mark.req("R-10.1-2")
async def test_any_principal_of_another_workspace_gets_not_found(world: World) -> None:
    submission = await world.pending()

    for principal in (STRANGER, STRANGER_KEY):  # the key gets `not_found`, not `forbidden`
        with pytest.raises(NotFoundError):
            await world.approvals.decide(
                principal, submission.submission_id, Decision(approve=True)
            )
    with pytest.raises(NotFoundError):
        await world.approvals.decide(BROWSER, SubmissionId("S-MSSNG0"), Decision(approve=True))

    quote_id = next(iter(world.quotes.quotes))
    assert (await world.view(quote_id)).status == "pending_approval"
    assert world.outbox.records == {}


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-8")
async def test_a_second_decision_is_an_invalid_state_and_leaves_the_first(world: World) -> None:
    approved = await world.approved()
    rejected_submission = await world.pending()
    await world.approvals.decide(
        BROWSER, rejected_submission.submission_id, Decision(approve=False)
    )

    for approval_id in (approved.approval_id, rejected_submission.submission_id):
        for approve in (True, False):
            with pytest.raises(InvalidStateError):
                await world.approvals.decide(BROWSER, approval_id, Decision(approve=approve))

    assert (await world.view(approved.quote_id)).status == "approved"
    assert len(world.outbox.records) == 1
    assert len(world.dispatcher.enqueued) == 1
    assert world.audit_codes(approved.quote_id).count("audit.approved") == 1


async def test_checks_run_in_the_order_workspace_then_principal_then_state(world: World) -> None:
    approved = await world.approved()  # already decided: the state check would fail

    with pytest.raises(NotFoundError):
        await world.approvals.decide(STRANGER_KEY, approved.approval_id, Decision(approve=True))
    with pytest.raises(ForbiddenError):
        await world.approvals.decide(API_KEY, approved.approval_id, Decision(approve=True))
    with pytest.raises(InvalidStateError):
        await world.approvals.decide(BROWSER, approved.approval_id, Decision(approve=True))


async def test_a_note_over_500_characters_is_refused_and_decides_nothing(world: World) -> None:
    submission = await world.pending()

    with pytest.raises(InvalidArgumentsError):
        await world.approvals.decide(
            BROWSER, submission.submission_id, Decision(approve=True, note="n" * 501)
        )

    assert world.outbox.records == {}
    accepted = await world.approvals.decide(
        BROWSER, submission.submission_id, Decision(approve=True, note="n" * 500)
    )
    assert accepted.status == "approved"


@pytest.mark.req("R-6-7")
async def test_the_event_id_is_created_once_however_often_the_transaction_function_runs(
    world: World,
) -> None:
    """A store that runs the function twice, as a retried transaction does, writes one event."""
    submission = await world.pending()

    class _RetryingRepository(MemoryQuoteRepository):
        async def update(self, quote_id: QuoteId, mutate: Callable[[Quote], Mutation]) -> Mutation:
            assert mutate(self.quotes[quote_id]) == mutate(self.quotes[quote_id])
            return await super().update(quote_id, mutate)

    retrying = _RetryingRepository(world.outbox)
    retrying.quotes, retrying.trails = world.quotes.quotes, world.quotes.trails
    approvals = ApprovalService(
        quotes=retrying,
        carriers=world.catalog,
        enqueuer=world.enqueuer,
        clock=world.clock,
        sweep=world.approvals_sweep,
        new_event=lambda: EVENT_1,
    )

    await approvals.decide(BROWSER, submission.submission_id, Decision(approve=True))

    assert list(world.outbox.records) == [EVENT_1]
    assert world.dispatcher.enqueued == [EVENT_1]
