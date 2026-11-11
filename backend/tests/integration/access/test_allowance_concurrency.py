"""The allowance is never exceeded when calls race for the last slots.

The emulator does not mimic production concurrency behaviour, so these tests assert
totals, never timing or the order of the admitted calls.
"""

import asyncio
import secrets
from datetime import UTC, datetime

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from tests.integration.access.conftest import FIRESTORE_HOST
from veranico.modules.access.application.allowances import Allowances
from veranico.modules.access.application.ports import CeilingReason
from veranico.modules.access.contracts import VisitorRef
from veranico.modules.access.domain.allowance import Limits
from veranico.modules.access.infrastructure.firestore_allowances import (
    COLLECTION,
    FirestoreAllowanceStore,
)
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock

pytestmark = [pytest.mark.integration, pytest.mark.req("R-10.3-1")]

NOW = datetime(2026, 11, 11, 21, 30, tzinfo=UTC)


class _NoCeiling:
    async def reached(self) -> CeilingReason | None:
        return None


@pytest.fixture
def allowances(firestore: AsyncClient) -> Allowances:
    return Allowances(
        FirestoreAllowanceStore(firestore),
        _NoCeiling(),
        FixedClock(NOW),
        limits=Limits(conversations=2, messages=15),
        boosted_limits=Limits(conversations=6, messages=60),
    )


async def _stored(firestore: AsyncClient, visitor: VisitorRef) -> tuple[int, int]:
    snapshot = await firestore.collection(COLLECTION).document(f"{visitor.ip_hash}-20261111").get()
    data = snapshot.to_dict()
    assert data is not None
    return data["conversations_used"], data["messages_used"]


async def test_forty_messages_started_together_admit_exactly_fifteen(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    visitor = VisitorRef(ip_hash=secrets.token_hex(32), boosted=False)
    await allowances.admit_message(visitor, new_conversation=True)

    admissions = await asyncio.gather(
        *(allowances.admit_message(visitor, new_conversation=False) for _ in range(40))
    )

    admitted = [admission for admission in admissions if admission.allowed]
    refused = [admission for admission in admissions if not admission.allowed]
    assert len(admitted) == 14  # fifteen with the message that opened the conversation
    assert len(refused) == 26
    assert {admission.reason for admission in refused} == {"visitor_allowance"}
    assert await _stored(firestore, visitor) == (1, 15)
    assert (await allowances.allowance(visitor)).messages_left == 0


async def test_ten_new_conversations_started_together_admit_exactly_two(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    visitor = VisitorRef(ip_hash=secrets.token_hex(32), boosted=False)

    admissions = await asyncio.gather(
        *(allowances.admit_message(visitor, new_conversation=True) for _ in range(10))
    )

    assert sum(admission.allowed for admission in admissions) == 2
    assert await _stored(firestore, visitor) == (2, 2)
    current = await allowances.allowance(visitor)
    assert (current.conversations_left, current.messages_left) == (0, 13)


async def test_two_instances_racing_for_one_visitor_admit_exactly_the_limit(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    # A second client with a second store: nothing in process is shared between the two,
    # as with two instances of the service.
    other_client = firestore_client(settings_for_tests(firestore_emulator_host=FIRESTORE_HOST))
    other = Allowances(
        FirestoreAllowanceStore(other_client),
        _NoCeiling(),
        FixedClock(NOW),
        limits=Limits(conversations=2, messages=15),
        boosted_limits=Limits(conversations=6, messages=60),
    )
    visitor = VisitorRef(ip_hash=secrets.token_hex(32), boosted=False)
    try:
        admissions = await asyncio.gather(
            *(
                instance.admit_message(visitor, new_conversation=False)
                for _ in range(15)
                for instance in (allowances, other)
            )
        )
    finally:
        await close_firestore(other_client)

    assert sum(admission.allowed for admission in admissions) == 15
    assert await _stored(firestore, visitor) == (0, 15)


async def test_two_visitors_racing_do_not_affect_each_other(
    allowances: Allowances, firestore: AsyncClient
) -> None:
    first = VisitorRef(ip_hash=secrets.token_hex(32), boosted=False)
    second = VisitorRef(ip_hash=secrets.token_hex(32), boosted=False)

    admissions = await asyncio.gather(
        *(
            allowances.admit_message(visitor, new_conversation=True)
            for _ in range(5)
            for visitor in (first, second)
        )
    )

    assert sum(admission.allowed for admission in admissions) == 4
    assert await _stored(firestore, first) == (2, 2)
    assert await _stored(firestore, second) == (2, 2)
