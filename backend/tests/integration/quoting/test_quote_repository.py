from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from google.cloud.firestore_v1.base_query import FieldFilter

from tests.fakes import builders
from tests.integration.quoting.conftest import TTL, Env
from veranico.modules.quoting.application.ports import QuoteAlreadyExistsError
from veranico.modules.quoting.contracts import AuditEntry, Decision, DeliveryAttempt
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.modules.quoting.infrastructure.mapping import (
    AUDIT,
    IDEMPOTENCY,
    OUTBOX,
    QUOTES,
    quote_document,
    quote_from_document,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import InvalidStateError, NotFoundError
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId

pytestmark = pytest.mark.integration


def _draft(env: Env, quote_id: str | None = None) -> Mutation:
    view = builders.quote_view(
        quote_id=quote_id or f"Q-{env.workspace_id[-6:].upper()}",
        workspace_id=env.workspace_id,
        priced=builders.priced_cover(gap_to_burn_cost_cents=-98_765),
        label="Fazenda São João",
        created_at=env.start,
    )
    return Quote.draft(
        quote_id=view.quote_id,
        workspace_id=view.workspace_id,
        created_at=view.created_at,
        location=view.location,
        dataset_id=view.dataset_id,
        cover=view.cover,
        priced=view.priced,
        actor="api_client",
        key_id="key-1",
        idempotency_ref="ref-1",
    )


@pytest.mark.req("R-6-1")
def test_a_quote_survives_the_document_mapping_unchanged() -> None:
    view = builders.quote_view(priced=builders.priced_cover(gap_to_burn_cost_cents=-98_765))
    quote = replace(
        Quote.draft(
            quote_id=view.quote_id,
            workspace_id=view.workspace_id,
            created_at=view.created_at,
            location=view.location,
            dataset_id=view.dataset_id,
            cover=view.cover,
            priced=view.priced,
            actor="agent",
            idempotency_ref="ref-1",
        )
        .quote.request_submission(
            submission_id=SubmissionId("S-000001"),
            carrier_id="carrier-1",
            actor="agent",
            at=view.created_at,
        )
        .quote,
        current_event_id=EventId("0190a8e0-0000-7000-8000-000000000001"),
    )

    document = quote_document(quote, view.created_at + TTL)

    assert quote_from_document(document) == quote
    assert document["priced"]["simulation"]["gap_to_burn_cost"] == {
        "amount_cents": -98_765,
        "currency": "BRL",
    }
    assert isinstance(document["priced"]["premium"]["premium"]["amount_cents"], int)
    assert document["priced"]["premium"]["rate_on_line"] == quote.priced.premium.rate_on_line
    assert document["submission_id"] == "S-000001"
    assert "audit" not in document


@pytest.mark.req("R-6-1")
async def test_a_stored_quote_is_read_back_unchanged_from_the_emulator(env: Env) -> None:
    mutation = _draft(env)

    await env.quotes.create(mutation)

    stored = await env.quotes.get(mutation.quote.quote_id)
    assert stored == mutation.quote
    assert stored is not None
    assert stored.priced.simulation.gap_to_burn_cost.amount_cents == -98_765
    assert await env.quotes.audit(mutation.quote.quote_id) == list(mutation.audit)
    assert await env.quotes.get(QuoteId("Q-MSSNG0")) is None


async def test_create_never_overwrites_and_writes_nothing_when_the_id_is_taken(
    env: Env,
) -> None:
    first = _draft(env)
    await env.quotes.create(first)
    second = replace(first, quote=replace(first.quote, idempotency_ref="ref-2"))

    with pytest.raises(QuoteAlreadyExistsError):
        await env.quotes.create(second)

    stored = await env.quotes.get(first.quote.quote_id)
    assert stored is not None
    assert stored.idempotency_ref == "ref-1"
    assert len(await env.quotes.audit(first.quote.quote_id)) == 1  # the batch is all or nothing


@pytest.mark.req("R-10.1-3")
async def test_every_written_document_carries_expires_at_as_a_timestamp(env: Env) -> None:
    await env.service.create_quote(env.api_key, env.command(), "key-a", "api_client")
    approval = await env.approved()
    expected = env.start + TTL
    quote_reference = env.client.collection(QUOTES).document(approval.quote_id)

    documents = [(await quote_reference.get()).to_dict()]
    documents += [entry.to_dict() async for entry in quote_reference.collection(AUDIT).stream()]
    event_id = await env.event_of(approval.quote_id)
    documents.append((await env.client.collection(OUTBOX).document(event_id).get()).to_dict())
    keys = env.client.collection(IDEMPOTENCY).where(
        filter=FieldFilter("workspace_id", "==", env.workspace_id)
    )
    documents += [key.to_dict() async for key in keys.stream()]

    assert len(documents) == 1 + 3 + 1 + 1
    for document in documents:
        assert document is not None
        assert isinstance(document["expires_at"], datetime)  # the type a TTL policy needs
        assert document["expires_at"] == expected


@pytest.mark.req("R-6-6")
async def test_the_audit_trail_reads_back_in_order_even_within_one_instant(env: Env) -> None:
    """The clock never moves here: order comes from the commits and from `seq`."""
    approval = await env.approved()
    event_id = await env.event_of(approval.quote_id)
    await env.service.record_delivery_attempt(
        DeliveryAttempt(
            event_id=event_id,
            attempt=1,
            status_code=200,
            error_code=None,
            duration_ms=12,
            receipt_id="R-000001",
        )
    )
    await env.service.append_audit(
        env.browser, approval.quote_id, "agent", Coded(code="audit.term_sheet_rendered")
    )

    view = await env.view(approval.quote_id)

    assert [(entry.actor, entry.action.code) for entry in view.audit] == [
        ("api_client", "audit.quote_created"),
        ("agent", "audit.submission_requested"),
        ("human", "audit.approved"),
        ("system", "audit.webhook_attempt"),
        ("carrier", "audit.receipt_recorded"),
        ("agent", "audit.term_sheet_rendered"),
    ]
    assert {entry.at for entry in view.audit} == {env.start}


@pytest.mark.req("R-6-6")
async def test_an_entry_with_an_earlier_time_is_read_first_whenever_it_was_written(
    env: Env,
) -> None:
    quote = await env.draft()
    earlier = AuditEntry(
        at=env.start - timedelta(seconds=1), actor="system", action=Coded(code="audit.earlier")
    )

    await env.quotes.update(quote.quote_id, lambda stored: Mutation(stored, (earlier,)))

    assert await env.audit_codes(quote.quote_id) == ["audit.earlier", "audit.quote_created"]


@pytest.mark.req("R-10.1-2")
async def test_lists_and_lookups_hold_only_what_matches(env: Env) -> None:
    mine = await env.pending()
    other_draft = await env.draft()
    theirs = await env.pending(env.stranger)

    listed = await env.quotes.list_for_workspace(env.workspace_id)
    found = await env.quotes.find_by_submission(mine.submission_id)

    assert {quote.workspace_id for quote in listed} == {env.workspace_id}
    assert len(listed) == 2
    assert other_draft.quote_id in {quote.quote_id for quote in listed}
    assert found is not None
    assert found.submission == mine
    foreign = await env.quotes.find_by_submission(theirs.submission_id)
    assert foreign is not None
    assert foreign.workspace_id == env.stranger.workspace_id
    assert await env.quotes.find_by_submission(SubmissionId("S-MSSNG0")) is None
    assert [a.approval_id for a in await env.service.list_approvals(env.browser, None)] == [
        mine.submission_id
    ]


async def test_an_update_of_a_missing_quote_or_event_is_not_found(env: Env) -> None:
    with pytest.raises(NotFoundError):
        await env.quotes.update(QuoteId("Q-MSSNG0"), lambda quote: Mutation(quote))
    with pytest.raises(NotFoundError):
        await env.quotes.update_for_event(
            EventId("0190a8e0-0000-7000-8000-00000000dead"), lambda quote, record: Mutation(quote)
        )


async def test_an_error_raised_by_the_mutation_writes_nothing(env: Env) -> None:
    approval = await env.approved()
    before = await env.view(approval.quote_id)

    with pytest.raises(InvalidStateError):
        await env.service.decide(env.browser, approval.approval_id, Decision(approve=False))

    assert await env.view(approval.quote_id) == before
    assert len(await env.outbox_documents()) == 1


async def test_a_mutation_that_changes_nothing_writes_nothing(env: Env) -> None:
    quote = await env.draft()
    submission = await env.service.request_submission(
        env.api_key, quote.quote_id, "carrier-1", "agent"
    )
    reference = env.client.collection(QUOTES).document(quote.quote_id)
    written = (await reference.get()).update_time

    again = await env.service.request_submission(env.api_key, quote.quote_id, "carrier-2", "agent")

    assert again == submission
    assert (await reference.get()).update_time == written


@pytest.mark.req("R-6-7")
async def test_an_approval_writes_state_audit_entry_and_outbox_event_in_one_commit(
    env: Env,
) -> None:
    """Documents written by one commit share its commit time; separate writes never do."""
    submission = await env.pending()
    env.dispatcher.failure = RuntimeError("queue unavailable")  # keep the outbox write alone

    approval = await env.service.decide(
        env.browser, submission.submission_id, Decision(approve=True, note="ok")
    )

    quote_reference = env.client.collection(QUOTES).document(approval.quote_id)
    quote = await quote_reference.get()
    entries = [entry async for entry in quote_reference.collection(AUDIT).stream()]
    (decision,) = [entry for entry in entries if entry.get("action.code") == "audit.approved"]
    event = await env.client.collection(OUTBOX).document(quote.get("current_event_id")).get()
    assert quote.get("status") == "approved"
    assert event.get("status") == "pending"
    assert event.get("event.data.submission_id") == submission.submission_id
    assert decision.get("note") == "ok"
    assert quote.update_time == decision.create_time == event.create_time
    earlier = [entry.create_time for entry in entries if entry.id != decision.id]
    assert all(time < quote.update_time for time in earlier)


@pytest.mark.req("R-6-7")
async def test_a_rejection_writes_no_outbox_document(env: Env) -> None:
    submission = await env.pending()

    approval = await env.service.decide(
        env.browser, submission.submission_id, Decision(approve=False)
    )

    assert approval.status == "rejected"
    assert await env.outbox_documents() == []
    assert env.dispatcher.enqueued == []
