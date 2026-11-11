from datetime import timedelta

import pytest

from tests.unit.quoting.world import API_KEY, BROWSER, STRANGER, World
from veranico.modules.quoting.application.approvals import ApprovalStatus
from veranico.modules.quoting.contracts import Decision, DeliveryAttempt
from veranico.shared.kernel.ids import QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal


@pytest.fixture
def world() -> World:
    return World()


async def _submit(world: World, quote_id: QuoteId) -> None:
    record = world.record_of(quote_id)
    receipt = DeliveryAttempt(
        event_id=record.event_id,
        attempt=1,
        status_code=200,
        error_code=None,
        duration_ms=40,
        receipt_id="R-000001",
    )
    at = world.clock.now()
    await world.quotes.update_for_event(
        record.event_id, lambda quote, stored: quote.record_attempt(stored, receipt, at=at)
    )


async def test_the_queue_filters_by_status_and_maps_submitted_to_approved(world: World) -> None:
    await world.draft()  # a quote without a submission is not an approval
    pending = await world.pending()
    world.clock.advance(timedelta(minutes=1))
    approved = await world.approved()
    world.clock.advance(timedelta(minutes=1))
    submitted = await world.approved()
    await _submit(world, submitted.quote_id)
    world.clock.advance(timedelta(minutes=1))
    rejected = await world.pending()
    await world.approvals.decide(BROWSER, rejected.submission_id, Decision(approve=False))

    async def ids(status: ApprovalStatus | None) -> list[str]:
        approvals = await world.approvals.list_approvals(BROWSER, status)
        assert all(status is None or approval.status == status for approval in approvals)
        return [approval.approval_id for approval in approvals]

    assert await ids("pending") == [pending.submission_id]
    assert await ids("approved") == [submitted.approval_id, approved.approval_id]
    assert await ids("rejected") == [rejected.submission_id]
    assert await ids(None) == [  # newest request first
        rejected.submission_id,
        submitted.approval_id,
        approved.approval_id,
        pending.submission_id,
    ]
    delivered = (await world.approvals.list_approvals(BROWSER, "approved"))[0]
    assert (delivered.status, delivered.delivery.status) == ("approved", "delivered")
    assert delivered.delivery.receipt_id == "R-000001"


async def test_an_approval_carries_the_figures_and_the_carrier_name(world: World) -> None:
    quote_id = await world.draft(label="Fazenda Santa Luzia")
    submission = await world.approvals.request_submission(API_KEY, quote_id, "carrier-2", "agent")

    (approval,) = await world.approvals.list_approvals(API_KEY, None)

    stored = world.quotes.quotes[quote_id]
    assert (approval.approval_id, approval.quote_id) == (submission.submission_id, quote_id)
    assert (approval.carrier_id, approval.carrier_name) == ("carrier-2", "Fake Carrier Two")
    assert approval.location_label == "Fazenda Santa Luzia"
    assert approval.limit == stored.cover.limit
    assert approval.premium == stored.priced.premium.premium
    assert approval.requested_at == submission.requested_at
    assert approval.delivery == submission.delivery


@pytest.mark.req("R-10.1-2")
async def test_the_queue_holds_nothing_of_another_workspace(world: World) -> None:
    mine = await world.pending(API_KEY)
    theirs = await world.pending(STRANGER)

    assert [a.approval_id for a in await world.approvals.list_approvals(BROWSER, None)] == [
        mine.submission_id
    ]
    assert [a.approval_id for a in await world.approvals.list_approvals(STRANGER, None)] == [
        theirs.submission_id
    ]
    nobody = Principal(workspace_id=WorkspaceId("ws-3"), kind="browser")
    assert await world.approvals.list_approvals(nobody, None) == []


@pytest.mark.req("R-7-5")
async def test_reading_the_queue_runs_the_sweep_first(world: World) -> None:
    await world.pending()

    await world.approvals.list_approvals(BROWSER, None)
    await world.approvals.list_approvals(BROWSER, "pending")

    assert world.sweeps == 2


@pytest.mark.req("R-7-5")
async def test_a_failing_sweep_is_swallowed_and_the_queue_is_still_read(world: World) -> None:
    pending = await world.pending()
    world.sweep_failure = RuntimeError("store unavailable")

    approvals = await world.approvals.list_approvals(BROWSER, None)

    assert [approval.approval_id for approval in approvals] == [pending.submission_id]
    assert world.sweeps == 1
