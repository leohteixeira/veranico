import secrets
from datetime import UTC, datetime, timedelta

import pytest
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.allowances import Allowances
from veranico.modules.access.application.ports import CeilingReason
from veranico.modules.access.contracts import VisitorRef
from veranico.modules.access.domain import visitor as visitor_rules
from veranico.modules.access.domain.allowance import Limits
from veranico.modules.access.infrastructure.firestore_allowances import (
    COLLECTION,
    FirestoreAllowanceStore,
)
from veranico.shared.kernel.clock import FixedClock

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 11, 21, 30, tzinfo=UTC)
MIDNIGHT = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
ADDRESS = "203.0.113.57"  # a documentation address (RFC 5737)


class _NoCeiling:
    async def reached(self) -> CeilingReason | None:
        return None


def _visitor(address: str = ADDRESS, *, boosted: bool = False) -> VisitorRef:
    # A fresh salt per call: every test has visitors of its own on the shared emulator.
    return VisitorRef(
        ip_hash=visitor_rules.hash_address(address, secrets.token_hex(16)), boosted=boosted
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def allowances(firestore: AsyncClient, clock: FixedClock) -> Allowances:
    return Allowances(
        FirestoreAllowanceStore(firestore),
        _NoCeiling(),
        clock,
        limits=Limits(conversations=2, messages=15),
        boosted_limits=Limits(conversations=6, messages=60),
    )


@pytest.mark.req("R-10.3-1")
async def test_messages_are_counted_and_refused_past_the_limits(allowances: Allowances) -> None:
    visitor = _visitor()

    fresh = await allowances.allowance(visitor)
    first = await allowances.admit_message(visitor, new_conversation=True)
    second = await allowances.admit_message(visitor, new_conversation=False)
    third = await allowances.admit_message(visitor, new_conversation=True)
    refused = await allowances.admit_message(visitor, new_conversation=True)
    current = await allowances.allowance(visitor)

    assert (fresh.conversations_left, fresh.messages_left, fresh.resets_at) == (2, 15, MIDNIGHT)
    assert first.allowed
    assert second.allowed
    assert third.allowed
    assert not refused.allowed
    assert refused.reason == "visitor_allowance"
    assert refused.allowance == current
    assert (current.conversations_left, current.messages_left) == (0, 12)


@pytest.mark.req("R-10.3-1", "R-10.3-7", "R-10.1-3")
async def test_the_document_is_named_by_the_hash_and_the_day_and_holds_no_address(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    visitor = _visitor()

    await allowances.admit_message(visitor, new_conversation=True)

    snapshot = await firestore.collection(COLLECTION).document(f"{visitor.ip_hash}-20261111").get()
    data = snapshot.to_dict()
    assert data is not None
    assert set(data) == {"conversations_used", "messages_used", "expires_at"}
    assert (data["conversations_used"], data["messages_used"]) == (1, 1)
    # A TTL policy needs a "Date and time" value; one day after the reset.
    assert isinstance(data["expires_at"], datetime)
    assert data["expires_at"] == MIDNIGHT + timedelta(days=1)
    assert ADDRESS not in snapshot.id
    assert ADDRESS not in repr(data)


@pytest.mark.req("R-10.3-1")
async def test_a_refused_message_writes_nothing(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    visitor = _visitor()
    reference = firestore.collection(COLLECTION).document(f"{visitor.ip_hash}-20261111")
    await allowances.admit_message(visitor, new_conversation=True)
    await allowances.admit_message(visitor, new_conversation=True)
    before = await reference.get()

    refused = await allowances.admit_message(visitor, new_conversation=True)

    after = await reference.get()
    assert not refused.allowed
    assert after.to_dict() == before.to_dict()
    assert after.update_time == before.update_time


@pytest.mark.req("R-10.3-1")
async def test_two_visitors_do_not_affect_each_other(allowances: Allowances) -> None:
    first, second = _visitor(), _visitor("203.0.113.58")
    await allowances.admit_message(first, new_conversation=True)
    await allowances.admit_message(first, new_conversation=True)

    untouched = await allowances.allowance(second)

    assert (untouched.conversations_left, untouched.messages_left) == (2, 15)
    assert (await allowances.admit_message(second, new_conversation=True)).allowed


@pytest.mark.req("R-10.3-1")
async def test_a_new_utc_day_starts_from_a_new_document(
    allowances: Allowances, clock: FixedClock, firestore: AsyncClient
) -> None:
    visitor = _visitor()
    await allowances.admit_message(visitor, new_conversation=True)
    await allowances.admit_message(visitor, new_conversation=True)

    clock.advance(MIDNIGHT - NOW)
    admission = await allowances.admit_message(visitor, new_conversation=True)

    assert admission.allowed
    assert admission.allowance is not None
    assert admission.allowance.conversations_left == 1
    assert admission.allowance.resets_at == MIDNIGHT + timedelta(days=1)
    collection = firestore.collection(COLLECTION)
    assert (await collection.document(f"{visitor.ip_hash}-20261111").get()).exists
    assert (await collection.document(f"{visitor.ip_hash}-20261112").get()).exists


@pytest.mark.req("R-10.3-2")
async def test_a_boost_gained_the_same_day_counts_against_the_same_document(
    allowances: Allowances,
) -> None:
    visitor = _visitor()
    boosted = visitor.model_copy(update={"boosted": True})
    await allowances.admit_message(visitor, new_conversation=True)
    await allowances.admit_message(visitor, new_conversation=True)

    admission = await allowances.admit_message(boosted, new_conversation=True)

    assert admission.allowed
    assert admission.allowance is not None
    assert (admission.allowance.conversations_left, admission.allowance.messages_left) == (3, 57)
