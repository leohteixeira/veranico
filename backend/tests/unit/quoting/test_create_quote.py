from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.pricing import FakePricingFacade
from tests.unit.quoting.memory import MemoryIdempotencyStore, MemoryQuoteRepository
from veranico.modules.climate.contracts import Location, LocationCandidates
from veranico.modules.pricing.contracts import CoverDefinition, PricedCover, SimulationOptions
from veranico.modules.quoting.application.ports import Reservation
from veranico.modules.quoting.application.quotes import QuoteService, idempotency_ref
from veranico.modules.quoting.contracts import CreateQuote, QuoteLocationInput, QuoteView
from veranico.modules.quoting.domain.fingerprint import fingerprint
from veranico.shared.kernel.clock import FixedClock
from veranico.shared.kernel.errors import (
    ConflictError,
    DatasetNotFoundError,
    DomainError,
    IdempotencyConflictError,
    InsufficientHistoryError,
    InvalidCoverError,
    OutsideCoverageError,
    WeatherSourceUnavailableError,
)
from veranico.shared.kernel.ids import DatasetId, QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal

pytestmark = pytest.mark.req("R-6-4")

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
LAT, LON = builders.LAT, builders.LON
# Not the cell the coordinates hash to, so a test can tell where the stored cell came from.
CLIMATE_CELL = "86a8100c7ffffff"
API_KEY = Principal(workspace_id=WorkspaceId("ws-1"), kind="api_key", key_id="key-1")
BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
OTHER_WORKSPACE = Principal(workspace_id=WorkspaceId("ws-2"), kind="api_key", key_id="key-2")


class _Climate(FakeClimateFacade):
    """The fake, answering coordinates with a cell and a region only `climate` knows."""

    async def resolve_location(
        self, query: str | None, lat: float | None, lon: float | None
    ) -> Location | LocationCandidates:
        resolved = await super().resolve_location(query, lat, lon)
        assert isinstance(resolved, Location)
        return resolved.model_copy(update={"h3_cell": CLIMATE_CELL, "admin_region": "Mato Grosso"})


class _Ids:
    """Predictable quote ids: Q-000001, Q-000002, ..."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> QuoteId:
        self.issued += 1
        return QuoteId(f"Q-{self.issued:06d}")


@dataclass
class World:
    service: QuoteService
    quotes: MemoryQuoteRepository
    idempotency: MemoryIdempotencyStore
    climate: _Climate
    pricing: FakePricingFacade
    clock: FixedClock
    dataset_id: DatasetId

    def calls(self, facade: FakeClimateFacade | FakePricingFacade, method: str) -> list[object]:
        return [arguments for name, arguments in facade.calls if name == method]


@pytest.fixture
def world() -> World:
    climate = _Climate()
    dataset = climate.add_series(builders.daily_series())
    pricing = FakePricingFacade()
    pricing.add_dataset(dataset.dataset_id)
    quotes = MemoryQuoteRepository()
    idempotency = MemoryIdempotencyStore()
    clock = FixedClock(NOW)
    service = QuoteService(
        quotes=quotes,
        idempotency=idempotency,
        climate=climate,
        pricing=pricing,
        clock=clock,
        new_id=_Ids(),
    )
    return World(service, quotes, idempotency, climate, pricing, clock, dataset.dataset_id)


def _command(
    *,
    lat: float = LAT,
    lon: float = LON,
    label: str | None = None,
    admin_region: str | None = None,
    cover: CoverDefinition | None = None,
) -> CreateQuote:
    return CreateQuote(
        location=QuoteLocationInput(lat=lat, lon=lon, label=label, admin_region=admin_region),
        cover=cover or builders.cover(),
        simulation=SimulationOptions(n=5_000, seed=7),
    )


async def test_a_new_key_resolves_ensures_and_prices_once_and_stores_one_draft(
    world: World,
) -> None:
    command = _command()

    view = await world.service.create_quote(API_KEY, command, "key-a", "api_client")

    assert world.calls(world.climate, "resolve_location") == [(None, LAT, LON)]
    assert world.calls(world.climate, "ensure_history") == [(LAT, LON)]
    assert world.calls(world.pricing, "price") == [
        (world.dataset_id, command.cover, command.simulation)
    ]
    assert list(world.quotes.quotes) == [view.quote_id]
    assert (view.status, view.submission) == ("draft", None)
    assert (view.workspace_id, view.created_at) == (WorkspaceId("ws-1"), NOW)
    assert view.dataset_id == world.dataset_id
    assert view.cover == command.cover
    assert view.location.h3_cell == CLIMATE_CELL
    assert (view.location.lat, view.location.lon) == (LAT, LON)
    (entry,) = view.audit
    assert (entry.at, entry.actor, entry.note) == (NOW, "api_client", None)
    assert entry.action.code == "audit.quote_created"
    assert entry.action.params == {"key_id": "key-1"}
    assert await world.service.get_quote(API_KEY, view.quote_id) == view


@pytest.mark.req("R-6-1")
async def test_the_stored_figures_equal_what_pricing_returned_field_by_field(world: World) -> None:
    command = _command()
    expected = builders.priced_cover(
        command.cover, dataset_id=world.dataset_id, options=command.simulation
    )

    view = await world.service.create_quote(API_KEY, command, "key-a", "api_client")

    for field in PricedCover.model_fields:
        assert getattr(view.priced, field) == getattr(expected, field), field
    stored = world.quotes.quotes[view.quote_id]
    assert stored.priced == expected
    assert stored.priced.simulation.n == 5_000


async def test_the_actor_passed_in_is_recorded_and_a_browser_has_no_key(world: World) -> None:
    view = await world.service.create_quote(BROWSER, _command(), "key-a", "agent")

    (entry,) = view.audit
    assert entry.actor == "agent"
    assert entry.action.params == {}


async def test_without_a_label_the_formatted_coordinates_are_stored(world: World) -> None:
    view = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")

    assert view.location.label == "-12.5500, -55.7200"
    assert view.location.admin_region == "Mato Grosso"  # from climate, absent in the request


async def test_a_label_and_a_region_sent_by_the_client_are_kept(world: World) -> None:
    command = _command(label="Fazenda Santa Luzia", admin_region="MT")

    view = await world.service.create_quote(API_KEY, command, "key-a", "api_client")

    assert view.location.label == "Fazenda Santa Luzia"
    assert view.location.admin_region == "MT"
    assert view.location.h3_cell == CLIMATE_CELL


async def test_a_replayed_key_returns_the_stored_quote_and_calls_nothing_again(
    world: World,
) -> None:
    first = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")
    climate_calls, pricing_calls = len(world.climate.calls), len(world.pricing.calls)
    world.clock.advance(timedelta(hours=1))

    replayed = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")

    assert replayed == first
    assert len(world.climate.calls) == climate_calls
    assert len(world.pricing.calls) == pricing_calls
    assert len(world.quotes.quotes) == 1
    assert len(world.quotes.trails[first.quote_id]) == 1


async def test_the_same_key_with_another_payload_is_an_idempotency_conflict(world: World) -> None:
    first = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")
    climate_calls = len(world.climate.calls)

    with pytest.raises(IdempotencyConflictError):
        await world.service.create_quote(API_KEY, _command(lat=LAT + 0.5), "key-a", "api_client")

    assert list(world.quotes.quotes) == [first.quote_id]
    assert len(world.climate.calls) == climate_calls


@pytest.mark.req("R-10.1-2")
async def test_the_same_key_in_another_workspace_creates_an_independent_quote(
    world: World,
) -> None:
    first = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")

    # Another payload under the same key text: no conflict, the keys never meet.
    second = await world.service.create_quote(
        OTHER_WORKSPACE, _command(label="Other"), "key-a", "api_client"
    )

    assert second.quote_id != first.quote_id
    assert (first.workspace_id, second.workspace_id) == (WorkspaceId("ws-1"), WorkspaceId("ws-2"))
    assert len(world.idempotency.reservations) == 2
    assert await world.service.create_quote(API_KEY, _command(), "key-a", "api_client") == first


async def test_a_key_reserved_by_a_request_that_died_is_completed_under_its_quote_id(
    world: World,
) -> None:
    command = _command()
    ref = idempotency_ref(API_KEY.workspace_id, "key-a")
    reserved = Reservation(API_KEY.workspace_id, fingerprint(command), QuoteId("Q-DEAD01"))
    await world.idempotency.reserve(ref, reserved, at=NOW)

    view = await world.service.create_quote(API_KEY, command, "key-a", "api_client")

    assert view.quote_id == QuoteId("Q-DEAD01")
    assert list(world.quotes.quotes) == [QuoteId("Q-DEAD01")]
    assert world.quotes.quotes[view.quote_id].idempotency_ref == ref
    assert world.idempotency.reservations == {ref: reserved}


async def test_without_a_key_every_call_creates_a_quote(world: World) -> None:
    first = await world.service.create_quote(API_KEY, _command(), None, "agent")
    second = await world.service.create_quote(API_KEY, _command(), None, "agent")

    assert first.quote_id != second.quote_id
    assert len(world.quotes.quotes) == 2
    assert world.idempotency.reservations == {}
    assert world.quotes.quotes[first.quote_id].idempotency_ref is None


@pytest.mark.parametrize("error", [OutsideCoverageError(), WeatherSourceUnavailableError()])
async def test_a_climate_error_propagates_and_stores_no_quote(
    world: World, error: DomainError
) -> None:
    world.climate.fail_with(error)

    with pytest.raises(type(error)):
        await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")

    assert world.quotes.quotes == {}
    assert world.pricing.calls == []


async def test_a_pricing_error_propagates_and_stores_no_quote(world: World) -> None:
    unknown_dataset = FakePricingFacade()
    short_history = FakePricingFacade()
    short_history.add_dataset(world.dataset_id, seasons=10)
    cases: list[tuple[FakePricingFacade, CoverDefinition, type[DomainError]]] = [
        (world.pricing, builders.cover(limit_cents=0), InvalidCoverError),
        (short_history, builders.cover(), InsufficientHistoryError),
        (unknown_dataset, builders.cover(), DatasetNotFoundError),
    ]

    for pricing, cover, expected in cases:
        service = QuoteService(
            quotes=world.quotes,
            idempotency=world.idempotency,
            climate=world.climate,
            pricing=pricing,
            clock=world.clock,
        )
        with pytest.raises(expected):
            await service.create_quote(API_KEY, _command(cover=cover), None, "api_client")

    assert world.quotes.quotes == {}


async def test_a_request_that_failed_can_be_retried_under_the_same_key(world: World) -> None:
    world.climate.fail_with(WeatherSourceUnavailableError())
    with pytest.raises(WeatherSourceUnavailableError):
        await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")
    world.climate.fail_with(None)

    view = await world.service.create_quote(API_KEY, _command(), "key-a", "api_client")

    assert list(world.quotes.quotes) == [view.quote_id]
    assert len(world.idempotency.reservations) == 1


async def test_a_duplicate_that_stores_first_wins_and_the_other_returns_its_quote(
    world: World,
) -> None:
    """Two requests with one key overlap: the second finishes while the first is pricing."""
    command = _command()
    inner: list[QuoteView] = []

    class _RacingPricing(FakePricingFacade):
        async def price(
            self, dataset_id: DatasetId, cover: CoverDefinition, options: SimulationOptions
        ) -> PricedCover:
            if not inner:
                inner.append(
                    await world.service.create_quote(API_KEY, command, "key-a", "api_client")
                )
            return await super().price(dataset_id, cover, options)

    racing = _RacingPricing()
    racing.add_dataset(world.dataset_id)
    outer_service = QuoteService(
        quotes=world.quotes,
        idempotency=world.idempotency,
        climate=world.climate,
        pricing=racing,
        clock=world.clock,
        new_id=_Ids(),
    )

    outer = await outer_service.create_quote(API_KEY, command, "key-a", "api_client")

    assert outer == inner[0]
    assert list(world.quotes.quotes) == [outer.quote_id]
    assert len(world.quotes.trails[outer.quote_id]) == 1
    assert len(world.idempotency.reservations) == 1


async def test_a_reserved_id_taken_by_another_quote_is_a_conflict_and_is_not_overwritten(
    world: World,
) -> None:
    other = await world.service.create_quote(API_KEY, _command(label="first"), "key-a", "agent")
    command = _command(label="second")
    ref = idempotency_ref(API_KEY.workspace_id, "key-b")
    await world.idempotency.reserve(
        ref, Reservation(API_KEY.workspace_id, fingerprint(command), other.quote_id), at=NOW
    )

    with pytest.raises(ConflictError):
        await world.service.create_quote(API_KEY, command, "key-b", "agent")

    assert world.quotes.quotes[other.quote_id].location.label == "first"
    assert len(world.quotes.quotes) == 1


async def test_an_unkeyed_quote_whose_id_is_taken_is_a_conflict_and_is_not_overwritten(
    world: World,
) -> None:
    first = await world.service.create_quote(API_KEY, _command(label="first"), None, "agent")
    colliding = QuoteService(
        quotes=world.quotes,
        idempotency=world.idempotency,
        climate=world.climate,
        pricing=world.pricing,
        clock=world.clock,
        new_id=lambda: first.quote_id,
    )

    with pytest.raises(ConflictError):
        await colliding.create_quote(OTHER_WORKSPACE, _command(label="second"), None, "agent")

    assert world.quotes.quotes[first.quote_id].location.label == "first"
    assert world.quotes.quotes[first.quote_id].workspace_id == WorkspaceId("ws-1")
