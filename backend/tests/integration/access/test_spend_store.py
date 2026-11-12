"""The spend ledger on the emulator.

The ledger documents are named by date, so they are shared by every run on the shared
emulator. Each test therefore lives on a random far-future date of its own (`spend_clock`
in `conftest.py`) and deletes the documents of that date afterwards.
"""

from datetime import timedelta

import pytest
from google.cloud.firestore import AsyncClient

from veranico.modules.access.application.spend import Spend
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.access.domain.cost import TokenPrices
from veranico.modules.access.infrastructure.firestore_spend import COLLECTION, FirestoreSpendStore
from veranico.shared.kernel.clock import FixedClock

pytestmark = pytest.mark.integration

MODEL = "invented-model"
PRICES = {MODEL: TokenPrices(input=1_000_000, output=2_000_000, cache_read=0, cache_write=0)}


def _usage(cost: int) -> ModelUsage:
    return ModelUsage(model=MODEL, input_tokens=cost, output_tokens=0)


@pytest.fixture
def spend(firestore: AsyncClient, spend_clock: FixedClock) -> Spend:
    return Spend(
        FirestoreSpendStore(firestore),
        spend_clock,
        prices=PRICES,
        day_ceiling_usd_micros=1_000,
        month_ceiling_usd_micros=2_500,
    )


async def _document(firestore: AsyncClient, name: str) -> dict[str, object] | None:
    return (await firestore.collection(COLLECTION).document(name).get()).to_dict()


@pytest.mark.req("R-10.3-3", "R-10.3-4")
async def test_the_first_write_of_a_day_creates_both_documents(
    spend: Spend, spend_clock: FixedClock, firestore: AsyncClient
) -> None:
    day = spend_clock.now().strftime("%Y-%m-%d")
    month = spend_clock.now().strftime("%Y-%m")
    assert await _document(firestore, f"day-{day}") is None
    assert (await spend.may_spend()).allowed
    assert await _document(firestore, f"day-{day}") is None  # the check writes nothing

    recorded = await spend.record(_usage(120))
    await spend.record(_usage(30))

    assert recorded.cost_usd_micros == 120
    assert await _document(firestore, f"day-{day}") == {"cost_usd_micros": 150, "calls": 2}
    assert await _document(firestore, f"month-{month}") == {"cost_usd_micros": 150, "calls": 2}


@pytest.mark.req("R-10.3-3")
async def test_spends_on_both_sides_of_midnight_land_in_two_days_and_one_month(
    spend: Spend, spend_clock: FixedClock, firestore: AsyncClient
) -> None:
    # `spend_clock` stands at 23:59:59 UTC on a day that is not the last of its month.
    first_day = spend_clock.now().strftime("%Y-%m-%d")
    month = spend_clock.now().strftime("%Y-%m")

    await spend.record(_usage(100))
    spend_clock.advance(timedelta(seconds=1))
    await spend.record(_usage(7))
    second_day = spend_clock.now().strftime("%Y-%m-%d")

    assert second_day != first_day
    assert await _document(firestore, f"day-{first_day}") == {"cost_usd_micros": 100, "calls": 1}
    assert await _document(firestore, f"day-{second_day}") == {"cost_usd_micros": 7, "calls": 1}
    assert await _document(firestore, f"month-{month}") == {"cost_usd_micros": 107, "calls": 2}


@pytest.mark.req("R-10.3-3")
async def test_the_ceilings_refuse_from_the_stored_totals(
    spend: Spend, spend_clock: FixedClock
) -> None:
    await spend.record(_usage(999))
    below = await spend.may_spend()
    await spend.record(_usage(1))
    at_day_ceiling = await spend.may_spend()
    spend_clock.advance(timedelta(seconds=1))  # the next day, the same month
    next_day = await spend.may_spend()
    await spend.record(_usage(900))
    await spend.record(_usage(600))
    both = await spend.may_spend()
    spend_clock.advance(timedelta(days=1))
    month_only = await spend.may_spend()

    assert below.allowed
    assert (at_day_ceiling.allowed, at_day_ceiling.reason) == (False, "day_ceiling")
    assert next_day.allowed
    assert (both.allowed, both.reason) == (False, "day_ceiling")
    assert (month_only.allowed, month_only.reason) == (False, "month_ceiling")
    assert {admission.allowance for admission in (below, at_day_ceiling, both, month_only)} == {
        None
    }
