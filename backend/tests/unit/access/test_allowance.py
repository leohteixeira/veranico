from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.access.memory import MemoryAllowanceStore, StubSpendCeilings
from veranico.modules.access.application.allowances import Allowances
from veranico.modules.access.contracts import Allowance, VisitorRef
from veranico.modules.access.domain import allowance as rules
from veranico.modules.access.domain.allowance import Limits, Usage
from veranico.shared.kernel.clock import FixedClock

NOW = datetime(2026, 11, 11, 21, 30, tzinfo=UTC)
MIDNIGHT = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
VISITOR = VisitorRef(ip_hash="a" * 64, boosted=False)
BOOSTED = VisitorRef(ip_hash="a" * 64, boosted=True)
OTHER = VisitorRef(ip_hash="b" * 64, boosted=False)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def store() -> MemoryAllowanceStore:
    return MemoryAllowanceStore()


@pytest.fixture
def ceilings() -> StubSpendCeilings:
    return StubSpendCeilings()


@pytest.fixture
def allowances(
    store: MemoryAllowanceStore, ceilings: StubSpendCeilings, clock: FixedClock
) -> Allowances:
    return Allowances(
        store,
        ceilings,
        clock,
        limits=Limits(conversations=2, messages=15),
        boosted_limits=Limits(conversations=6, messages=60),
    )


def _left(allowance: Allowance | None) -> tuple[int, int]:
    assert allowance is not None
    return allowance.conversations_left, allowance.messages_left


@pytest.mark.req("R-10.3-1")
async def test_a_new_visitor_has_the_default_allowance_until_the_next_utc_midnight(
    allowances: Allowances,
) -> None:
    allowance = await allowances.allowance(VISITOR)

    assert allowance == Allowance(
        conversations_left=2, messages_left=15, resets_at=MIDNIGHT, boosted=False
    )


@pytest.mark.req("R-10.3-2")
async def test_a_boosted_visitor_has_the_larger_allowance(allowances: Allowances) -> None:
    allowance = await allowances.allowance(BOOSTED)

    assert allowance == Allowance(
        conversations_left=6, messages_left=60, resets_at=MIDNIGHT, boosted=True
    )


@pytest.mark.req("R-10.3-1")
async def test_a_first_message_consumes_one_conversation_and_one_message(
    allowances: Allowances,
) -> None:
    admission = await allowances.admit_message(VISITOR, new_conversation=True)

    assert admission.allowed
    assert admission.reason == "ok"
    assert _left(admission.allowance) == (1, 14)
    assert _left(await allowances.allowance(VISITOR)) == (1, 14)


@pytest.mark.req("R-10.3-1")
async def test_a_further_message_in_the_conversation_consumes_one_message_only(
    allowances: Allowances,
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)

    admission = await allowances.admit_message(VISITOR, new_conversation=False)

    assert admission.allowed
    assert _left(admission.allowance) == (1, 13)


@pytest.mark.req("R-10.3-1")
async def test_the_third_new_conversation_is_refused_and_consumes_nothing(
    allowances: Allowances, store: MemoryAllowanceStore
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    await allowances.admit_message(VISITOR, new_conversation=True)
    writes = store.writes

    refused = await allowances.admit_message(VISITOR, new_conversation=True)
    in_conversation = await allowances.admit_message(VISITOR, new_conversation=False)

    assert not refused.allowed
    assert refused.reason == "visitor_allowance"
    assert _left(refused.allowance) == (0, 13)  # the current allowance, unchanged
    assert store.writes == writes + 1  # only the message inside a conversation was counted
    assert in_conversation.allowed
    assert _left(in_conversation.allowance) == (0, 12)


@pytest.mark.req("R-10.3-1")
async def test_the_sixteenth_message_is_refused(
    allowances: Allowances, store: MemoryAllowanceStore
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    for _ in range(14):
        assert (await allowances.admit_message(VISITOR, new_conversation=False)).allowed

    refused = await allowances.admit_message(VISITOR, new_conversation=False)

    assert not refused.allowed
    assert refused.reason == "visitor_allowance"
    assert _left(refused.allowance) == (1, 0)
    assert store.usages[(VISITOR.ip_hash, "20261111")] == Usage(1, 15)
    # A new conversation needs a message too: refused although one conversation is left.
    assert not (await allowances.admit_message(VISITOR, new_conversation=True)).allowed
    assert _left(await allowances.allowance(VISITOR)) == (1, 0)


@pytest.mark.req("R-10.3-1")
async def test_the_allowance_is_whole_again_after_midnight_utc(
    allowances: Allowances, clock: FixedClock
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    await allowances.admit_message(VISITOR, new_conversation=True)

    clock.advance(MIDNIGHT - NOW - timedelta(seconds=1))
    before = await allowances.allowance(VISITOR)
    clock.advance(timedelta(seconds=1))
    after = await allowances.allowance(VISITOR)
    admission = await allowances.admit_message(VISITOR, new_conversation=True)

    assert _left(before) == (0, 13)
    assert before.resets_at == MIDNIGHT
    assert _left(after) == (2, 15)
    assert after.resets_at == MIDNIGHT + timedelta(days=1)
    assert admission.allowed
    assert _left(admission.allowance) == (1, 14)


@pytest.mark.req("R-10.3-1")
async def test_the_day_is_a_utc_day_whatever_the_offset_of_the_clock() -> None:
    # 23:30 on the 11th in São Paulo is 02:30 UTC on the 12th.
    local = datetime(2026, 11, 11, 23, 30, tzinfo=UTC) + timedelta(hours=3)

    assert rules.day_key(local) == "20261112"
    assert rules.day_key(local.astimezone(datetime.now().astimezone().tzinfo)) == "20261112"
    assert rules.resets_at(local) == datetime(2026, 11, 13, tzinfo=UTC)
    assert rules.resets_at(MIDNIGHT) == MIDNIGHT + timedelta(days=1)


@pytest.mark.req("R-10.3-1")
async def test_the_usage_document_expires_one_day_after_the_reset(
    allowances: Allowances, store: MemoryAllowanceStore
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)

    assert store.expires_at[(VISITOR.ip_hash, "20261111")] == MIDNIGHT + timedelta(days=1)


@pytest.mark.req("R-10.3-2")
async def test_a_boost_gained_the_same_day_keeps_the_counts_already_used(
    allowances: Allowances,
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    await allowances.admit_message(VISITOR, new_conversation=True)
    assert not (await allowances.admit_message(VISITOR, new_conversation=True)).allowed

    admission = await allowances.admit_message(BOOSTED, new_conversation=True)

    assert admission.allowed
    assert _left(admission.allowance) == (3, 57)  # 6 and 60, less the 3 and 3 used
    assert admission.allowance is not None
    assert admission.allowance.boosted
    # Without the code again, the smaller limits apply to the same counts.
    assert _left(await allowances.allowance(VISITOR)) == (0, 12)


@pytest.mark.req("R-10.3-1")
async def test_allowance_never_consumes(
    allowances: Allowances, store: MemoryAllowanceStore
) -> None:
    for _ in range(20):
        await allowances.allowance(VISITOR)

    assert store.writes == 0
    assert _left(await allowances.allowance(VISITOR)) == (2, 15)


@pytest.mark.req("R-10.3-1")
async def test_two_visitors_do_not_affect_each_other(allowances: Allowances) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    await allowances.admit_message(VISITOR, new_conversation=True)

    assert _left(await allowances.allowance(OTHER)) == (2, 15)
    assert (await allowances.admit_message(OTHER, new_conversation=True)).allowed


@pytest.mark.req("R-10.3-3")
@pytest.mark.parametrize("reason", ["day_ceiling", "month_ceiling"])
async def test_a_reached_ceiling_refuses_the_message_and_consumes_nothing(
    allowances: Allowances,
    store: MemoryAllowanceStore,
    ceilings: StubSpendCeilings,
    reason: str,
) -> None:
    await allowances.admit_message(VISITOR, new_conversation=True)
    ceilings.reason = reason  # type: ignore[assignment]  # parametrised over the two literals

    admission = await allowances.admit_message(VISITOR, new_conversation=True)

    assert not admission.allowed
    assert admission.reason == reason
    assert _left(admission.allowance) == (1, 14)  # always an allowance, and it is kept
    assert store.writes == 1
    ceilings.reason = None
    assert (await allowances.admit_message(VISITOR, new_conversation=True)).allowed
