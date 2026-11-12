from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from tests.unit.quoting.memory import MemoryIdempotencyStore, MemoryQuoteRepository
from veranico.modules.pricing.contracts import SimulationOptions
from veranico.modules.quoting.application.quotes import QuoteService
from veranico.modules.quoting.contracts import AuditEntry, CreateQuote, QuoteLocationInput
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
OWNER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
OWNER_KEY = Principal(workspace_id=WorkspaceId("ws-1"), kind="api_key", key_id="key-1")
STRANGER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")
RENDERED = Coded(code="audit.term_sheet_rendered", params={"locale": "pt-BR"})


class World:
    def __init__(self) -> None:
        climate = FakeClimateFacade()
        dataset = climate.add_series(builders.daily_series())
        pricing = FakePricingFacade()
        pricing.add_dataset(dataset.dataset_id)
        self.quotes = MemoryQuoteRepository()
        self.clock = FixedClock(NOW)
        self.service = QuoteService(
            quotes=self.quotes,
            idempotency=MemoryIdempotencyStore(),
            climate=climate,
            pricing=pricing,
            clock=self.clock,
        )

    async def quote(self, principal: Principal = OWNER_KEY, label: str | None = None) -> QuoteId:
        command = CreateQuote(
            location=QuoteLocationInput(lat=builders.LAT, lon=builders.LON, label=label),
            cover=builders.cover(),
            simulation=SimulationOptions(n=1_000),
        )
        view = await self.service.create_quote(principal, command, None, "api_client")
        return view.quote_id


@pytest.fixture
def world() -> World:
    return World()


@pytest.mark.req("R-6-1")
async def test_a_quote_is_read_by_any_principal_of_its_workspace(world: World) -> None:
    quote_id = await world.quote(OWNER_KEY)

    by_browser = await world.service.get_quote(OWNER, quote_id)
    by_key = await world.service.get_quote(OWNER_KEY, quote_id)

    assert by_browser == by_key
    assert (by_browser.quote_id, by_browser.workspace_id) == (quote_id, WorkspaceId("ws-1"))
    assert [entry.action.code for entry in by_browser.audit] == ["audit.quote_created"]


@pytest.mark.req("R-10.1-2")
async def test_a_quote_of_another_workspace_answers_as_a_missing_one(world: World) -> None:
    quote_id = await world.quote(OWNER_KEY)

    with pytest.raises(NotFoundError) as foreign:
        await world.service.get_quote(STRANGER, quote_id)
    with pytest.raises(NotFoundError) as missing:
        await world.service.get_quote(OWNER, QuoteId("Q-MSSNG0"))

    assert str(foreign.value) == str(missing.value)


@pytest.mark.req("R-6-6")
async def test_the_audit_trail_is_read_oldest_first_keeping_the_order_inside_a_mutation(
    world: World,
) -> None:
    quote_id = await world.quote()
    later = NOW + timedelta(minutes=2)
    earlier = NOW + timedelta(minutes=1)
    # Stored out of order, with two entries of one instant, as two mutations would leave them.
    world.quotes.trails[quote_id].extend(
        [
            AuditEntry(at=later, actor="system", action=Coded(code="audit.webhook_attempt")),
            AuditEntry(at=later, actor="carrier", action=Coded(code="audit.receipt_recorded")),
            AuditEntry(at=earlier, actor="human", action=Coded(code="audit.approved")),
        ]
    )

    view = await world.service.get_quote(OWNER, quote_id)

    assert [entry.action.code for entry in view.audit] == [
        "audit.quote_created",
        "audit.approved",
        "audit.webhook_attempt",
        "audit.receipt_recorded",
    ]


async def test_quotes_are_listed_newest_first_with_their_summary(world: World) -> None:
    oldest = await world.quote(label="oldest")
    world.clock.advance(timedelta(minutes=1))
    middle = await world.quote(label="middle")
    world.clock.advance(timedelta(minutes=1))
    newest = await world.quote(label="newest")

    summaries = await world.service.list_quotes(OWNER)

    assert [summary.quote_id for summary in summaries] == [newest, middle, oldest]
    first = summaries[0]
    stored = world.quotes.quotes[newest]
    assert (first.created_at, first.status) == (NOW + timedelta(minutes=2), "draft")
    assert first.location_label == "newest"
    assert first.premium == stored.priced.premium.premium


@pytest.mark.req("R-10.1-2")
async def test_the_list_holds_nothing_of_another_workspace(world: World) -> None:
    mine = await world.quote(OWNER_KEY)
    theirs = await world.quote(STRANGER)

    assert [summary.quote_id for summary in await world.service.list_quotes(OWNER)] == [mine]
    assert [summary.quote_id for summary in await world.service.list_quotes(STRANGER)] == [theirs]
    nobody = Principal(workspace_id=WorkspaceId("ws-3"), kind="browser")
    assert await world.service.list_quotes(nobody) == []


@pytest.mark.req("R-6-6")
async def test_an_appended_entry_carries_the_time_the_actor_and_the_action(world: World) -> None:
    quote_id = await world.quote()
    world.clock.advance(timedelta(minutes=3))

    await world.service.append_audit(OWNER, quote_id, "agent", RENDERED)

    view = await world.service.get_quote(OWNER, quote_id)
    assert view.audit[-1] == AuditEntry(
        at=NOW + timedelta(minutes=3), actor="agent", action=RENDERED, note=None
    )
    assert len(view.audit) == 2
    assert view.status == "draft"


@pytest.mark.req("R-10.1-2")
async def test_nothing_is_appended_to_a_quote_of_another_workspace_or_a_missing_one(
    world: World,
) -> None:
    quote_id = await world.quote()

    with pytest.raises(NotFoundError):
        await world.service.append_audit(STRANGER, quote_id, "agent", RENDERED)
    with pytest.raises(NotFoundError):
        await world.service.append_audit(OWNER, QuoteId("Q-MSSNG0"), "agent", RENDERED)

    assert len(world.quotes.trails[quote_id]) == 1
