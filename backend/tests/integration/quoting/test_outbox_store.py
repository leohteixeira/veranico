from datetime import timedelta

import pytest

from tests.integration.quoting.conftest import RETRY_WINDOW_SECONDS, SWEEP_AGE_SECONDS, Env
from veranico.modules.quoting.contracts import DeliveryAttempt, DeliveryState
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId

pytestmark = pytest.mark.integration

UNKNOWN_EVENT = EventId("0190a8e0-0000-7000-8000-00000000dead")


def _attempt(event_id: EventId, number: int, receipt_id: str | None = None) -> DeliveryAttempt:
    return DeliveryAttempt(
        event_id=event_id,
        attempt=number,
        status_code=200 if receipt_id else 503,
        error_code=None if receipt_id else "delivery_failed",
        duration_ms=31,
        receipt_id=receipt_id,
    )


async def test_an_approved_event_is_stored_enqueued_and_read_back(env: Env) -> None:
    approval = await env.approved()

    record = await env.record_of(approval.quote_id)

    assert env.dispatcher.enqueued == [record.event_id]
    assert (record.status, record.quote_id) == ("enqueued", approval.quote_id)
    assert (record.created_at, record.enqueued_at) == (env.start, env.start)
    assert (record.recorded_attempts, record.attempt_base) == ((), 0)
    assert (record.last_attempt_at, record.next_attempt_at) == (None, None)
    event = await env.service.load_event(record.event_id)
    assert event == record.event
    assert (event.occurred_at, event.workspace_id) == (env.start, env.workspace_id)
    assert event.data.submission_id == approval.approval_id
    assert event.data.premium == approval.premium
    assert await env.outbox.get(UNKNOWN_EVENT) is None
    with pytest.raises(NotFoundError):
        await env.service.load_event(UNKNOWN_EVENT)


async def test_marking_enqueued_moves_only_a_pending_record(env: Env) -> None:
    approval = await env.never_enqueued()
    event_id = await env.event_of(approval.quote_id)
    later = env.start + timedelta(minutes=1)

    await env.outbox.mark_enqueued(event_id, later)
    await env.outbox.mark_enqueued(event_id, later + timedelta(minutes=1))  # already enqueued
    await env.outbox.mark_enqueued(UNKNOWN_EVENT, later)  # nothing to mark, nothing created

    record = await env.record_of(approval.quote_id)
    assert (record.status, record.enqueued_at) == ("enqueued", later)
    assert await env.outbox.get(UNKNOWN_EVENT) is None


async def test_records_are_listed_by_status(env: Env) -> None:
    pending = await env.never_enqueued()
    enqueued = await env.approved()
    pending_event = await env.event_of(pending.quote_id)
    enqueued_event = await env.event_of(enqueued.quote_id)

    listed_pending = {record.event_id for record in await env.outbox.list_by_status("pending")}
    listed_enqueued = {record.event_id for record in await env.outbox.list_by_status("enqueued")}

    # The emulator is shared: other records may be listed too, these two are told apart.
    assert pending_event in listed_pending
    assert pending_event not in listed_enqueued
    assert enqueued_event in listed_enqueued
    assert enqueued_event not in listed_pending


@pytest.mark.req("R-7-4")
@pytest.mark.req("R-6-6")
async def test_attempts_are_recorded_once_each_and_a_receipt_submits_the_quote(
    env: Env,
) -> None:
    approval = await env.approved()
    event_id = await env.event_of(approval.quote_id)
    env.clock.advance(timedelta(seconds=5))

    await env.service.record_delivery_attempt(_attempt(event_id, 1))
    await env.service.record_delivery_attempt(_attempt(event_id, 1))  # the same attempt again

    view = await env.view(approval.quote_id)
    assert view.status == "approved"
    assert view.submission is not None
    assert view.submission.delivery == DeliveryState(
        status="delivering", attempts=1, receipt_id=None, last_error_code="delivery_failed"
    )
    assert (await env.audit_codes(approval.quote_id)).count("audit.webhook_attempt") == 1
    record = await env.record_of(approval.quote_id)
    assert (record.recorded_attempts, record.last_attempt_at) == (
        (1,),
        env.start + timedelta(seconds=5),
    )

    await env.service.record_delivery_attempt(_attempt(event_id, 2, "R-000001"))

    view = await env.view(approval.quote_id)
    assert view.status == "submitted"
    assert view.submission is not None
    assert view.submission.delivery == DeliveryState(
        status="delivered", attempts=2, receipt_id="R-000001", last_error_code=None
    )
    assert (await env.record_of(approval.quote_id)).status == "delivered"
    assert (await env.audit_codes(approval.quote_id))[-2:] == [
        "audit.webhook_attempt",
        "audit.receipt_recorded",
    ]


@pytest.mark.req("R-7-6")
async def test_an_abandoned_delivery_is_recorded_once_and_can_be_redelivered(env: Env) -> None:
    approval = await env.approved()
    event_id = await env.event_of(approval.quote_id)
    await env.service.record_delivery_attempt(_attempt(event_id, 1))

    await env.service.record_delivery_abandoned(event_id)
    await env.service.record_delivery_abandoned(event_id)

    view = await env.view(approval.quote_id)
    assert view.status == "approved"
    assert view.submission is not None
    assert view.submission.delivery.status == "abandoned"
    assert (await env.audit_codes(approval.quote_id)).count("audit.delivery_abandoned") == 1

    redelivered = await env.service.redeliver(env.browser, approval.approval_id)

    record = await env.record_of(approval.quote_id)
    assert redelivered.delivery.status == "delivering"
    assert (record.event_id, record.status, record.attempt_base) == (event_id, "enqueued", 1)
    assert env.dispatcher.enqueued == [event_id, event_id]
    assert (await env.audit_codes(approval.quote_id))[-1] == "audit.redelivery_requested"
    with pytest.raises(NotFoundError):
        await env.service.redeliver(env.stranger, approval.approval_id)


@pytest.mark.req("R-7-5")
async def test_the_sweep_enqueues_a_committed_event_that_was_never_enqueued(env: Env) -> None:
    approval = await env.never_enqueued()
    event_id = await env.event_of(approval.quote_id)
    env.clock.advance(timedelta(seconds=SWEEP_AGE_SECONDS - 1))

    await env.service.sweep_outbox(SWEEP_AGE_SECONDS)

    assert env.dispatcher.enqueued == []  # younger than the age
    assert (await env.record_of(approval.quote_id)).status == "pending"

    env.clock.advance(timedelta(seconds=1))
    count = await env.service.sweep_outbox(SWEEP_AGE_SECONDS)
    await env.service.sweep_outbox(SWEEP_AGE_SECONDS)

    # The outbox is shared with other runs, so the count is a lower bound here; the unit
    # tests pin it exactly.
    assert count >= 1
    assert env.dispatcher.enqueued.count(event_id) == 1
    record = await env.record_of(approval.quote_id)
    assert (record.status, record.enqueued_at) == (
        "enqueued",
        env.start + timedelta(seconds=SWEEP_AGE_SECONDS),
    )


@pytest.mark.req("R-7-13")
async def test_the_sweep_abandons_a_delivery_silent_past_the_retry_window(env: Env) -> None:
    silent = await env.approved()
    attempted = await env.approved()
    attempted_event = await env.event_of(attempted.quote_id)
    env.clock.advance(timedelta(seconds=RETRY_WINDOW_SECONDS))
    await env.service.record_delivery_attempt(_attempt(attempted_event, 1))

    await env.service.sweep_outbox(SWEEP_AGE_SECONDS)  # exactly the window: nothing is silent

    assert (await env.record_of(silent.quote_id)).status == "enqueued"

    env.clock.advance(timedelta(seconds=1))
    await env.service.sweep_outbox(SWEEP_AGE_SECONDS)
    await env.service.sweep_outbox(SWEEP_AGE_SECONDS)

    view = await env.view(silent.quote_id)
    assert view.status == "approved"
    assert view.submission is not None
    assert view.submission.delivery.status == "abandoned"
    assert (await env.record_of(silent.quote_id)).status == "abandoned"
    assert (await env.audit_codes(silent.quote_id)).count("audit.delivery_abandoned") == 1
    assert (view.audit[-1].actor, view.audit[-1].action.params) == ("system", {"attempts": 0})
    # The other delivery had an attempt inside the window and is left alone.
    assert (await env.record_of(attempted.quote_id)).status == "enqueued"
    listed = await env.service.list_approvals(env.browser, "approved")
    assert {a.approval_id: a.delivery.status for a in listed} == {
        silent.approval_id: "abandoned",
        attempted.approval_id: "delivering",
    }
