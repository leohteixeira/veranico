"""No update is lost when many calls are charged at once. Totals are asserted, not timing."""

import asyncio

import pytest
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.spend import Spend
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.access.domain.cost import TokenPrices
from veranico.modules.access.infrastructure.firestore_spend import COLLECTION, FirestoreSpendStore
from veranico.shared.kernel.clock import FixedClock

pytestmark = [pytest.mark.integration, pytest.mark.req("R-10.3-3")]

MODEL = "invented-model"
PRICES = {MODEL: TokenPrices(input=1_000_000, output=2_000_000, cache_read=0, cache_write=0)}


async def test_fifty_spends_started_together_leave_the_exact_sum(
    firestore: AsyncClient, spend_clock: FixedClock
) -> None:
    spend = Spend(
        FirestoreSpendStore(firestore),
        spend_clock,
        prices=PRICES,
        day_ceiling_usd_micros=10**12,
        month_ceiling_usd_micros=10**12,
    )
    usages = [
        ModelUsage(model=MODEL, input_tokens=100 + number, output_tokens=number)
        for number in range(50)
    ]

    recorded = await asyncio.gather(*(spend.record(usage) for usage in usages))

    expected = sum(100 + number + 2 * number for number in range(50))
    assert sum(item.cost_usd_micros for item in recorded) == expected
    day = spend_clock.now().strftime("%Y-%m-%d")
    month = spend_clock.now().strftime("%Y-%m")
    collection = firestore.collection(COLLECTION)
    assert (await collection.document(f"day-{day}").get()).to_dict() == {
        "cost_usd_micros": expected,
        "calls": 50,
    }
    assert (await collection.document(f"month-{month}").get()).to_dict() == {
        "cost_usd_micros": expected,
        "calls": 50,
    }
