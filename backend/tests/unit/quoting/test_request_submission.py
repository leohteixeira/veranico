from dataclasses import replace

import pytest

from tests.unit.quoting.world import API_KEY, BROWSER, STRANGER, World
from veranico.modules.quoting.contracts import Decision
from veranico.shared.kernel.errors import InvalidStateError, NotFoundError, UnknownCarrierError
from veranico.shared.kernel.ids import QuoteId, SubmissionId

pytestmark = pytest.mark.req("R-6-5")


@pytest.fixture
def world() -> World:
    return World()


@pytest.mark.req("R-6-2")
@pytest.mark.req("R-6-6")
async def test_a_request_creates_a_pending_approval_with_one_audit_entry(world: World) -> None:
    quote_id = await world.draft()

    submission = await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")

    assert submission.submission_id == SubmissionId("S-000001")
    assert (submission.carrier_id, submission.requested_at) == ("carrier-1", world.clock.now())
    assert submission.delivery.status == "not_started"
    view = await world.view(quote_id)
    assert view.status == "pending_approval"
    assert view.submission == submission
    entry = view.audit[-1]
    assert (entry.actor, entry.action.code) == ("agent", "audit.submission_requested")
    assert entry.action.params == {"carrier_id": "carrier-1", "key_id": "key-1"}
    assert world.outbox.records == {}
    assert world.dispatcher.enqueued == []


async def test_a_browser_request_carries_no_key_parameter(world: World) -> None:
    quote_id = await world.draft(BROWSER)

    await world.approvals.request_submission(BROWSER, quote_id, "carrier-2", "agent")

    assert (await world.view(quote_id)).audit[-1].action.params == {"carrier_id": "carrier-2"}


async def test_a_repeated_request_returns_the_same_submission_even_for_another_carrier(
    world: World,
) -> None:
    quote_id = await world.draft()
    first = await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")

    same = await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")
    other_carrier = await world.approvals.request_submission(
        BROWSER, quote_id, "carrier-2", "api_client"
    )
    unknown_carrier = await world.approvals.request_submission(API_KEY, quote_id, "nope", "agent")

    assert same == other_carrier == unknown_carrier == first
    assert world.audit_codes(quote_id) == ["audit.quote_created", "audit.submission_requested"]


async def test_a_repeated_request_still_returns_the_submission_after_the_decision(
    world: World,
) -> None:
    approval = await world.approved()

    submission = await world.approvals.request_submission(
        BROWSER, approval.quote_id, "carrier-1", "agent"
    )

    assert submission.submission_id == approval.approval_id
    assert submission.delivery.status == "delivering"
    assert (await world.view(approval.quote_id)).status == "approved"


async def test_a_carrier_absent_from_the_catalogue_is_unknown_and_changes_nothing(
    world: World,
) -> None:
    quote_id = await world.draft()

    with pytest.raises(UnknownCarrierError):
        await world.approvals.request_submission(API_KEY, quote_id, "carrier-9", "agent")

    view = await world.view(quote_id)
    assert (view.status, view.submission) == ("draft", None)
    assert world.audit_codes(quote_id) == ["audit.quote_created"]


@pytest.mark.req("R-6-2")
async def test_a_quote_that_is_not_a_draft_and_has_no_submission_is_an_invalid_state(
    world: World,
) -> None:
    """Unreachable through the facade; the rule still holds on a stored quote in that shape."""
    quote_id = await world.draft()
    world.quotes.quotes[quote_id] = replace(world.quotes.quotes[quote_id], status="rejected")

    with pytest.raises(InvalidStateError):
        await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")
    with pytest.raises(InvalidStateError):  # the state is judged before the carrier
        await world.approvals.request_submission(API_KEY, quote_id, "carrier-9", "agent")


@pytest.mark.req("R-10.1-2")
async def test_a_quote_of_another_workspace_or_a_missing_one_is_not_found(world: World) -> None:
    quote_id = await world.draft()

    with pytest.raises(NotFoundError):
        await world.approvals.request_submission(STRANGER, quote_id, "carrier-1", "agent")
    with pytest.raises(NotFoundError):  # not `unknown_carrier`: existence does not leak
        await world.approvals.request_submission(STRANGER, quote_id, "carrier-9", "agent")
    with pytest.raises(NotFoundError):
        await world.approvals.request_submission(API_KEY, QuoteId("Q-MSSNG0"), "carrier-1", "agent")

    assert (await world.view(quote_id)).status == "draft"


@pytest.mark.req("R-6-3")
async def test_requesting_never_decides(world: World) -> None:
    """A rejected quote stays rejected however often a submission is requested again."""
    quote_id = await world.draft()
    submission = await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")
    await world.approvals.decide(BROWSER, submission.submission_id, Decision(approve=False))

    again = await world.approvals.request_submission(API_KEY, quote_id, "carrier-1", "agent")

    assert again.submission_id == submission.submission_id
    assert (await world.view(quote_id)).status == "rejected"
    assert world.outbox.records == {}
