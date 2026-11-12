"""Create, read and audit use cases."""

import hashlib
from collections.abc import Callable

from veranico.modules.climate.contracts import ClimateFacade, Location
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.application.ports import (
    IdempotencyStore,
    QuoteAlreadyExistsError,
    QuoteRepository,
    Reservation,
)
from veranico.modules.quoting.contracts import (
    Actor,
    AuditEntry,
    CreateQuote,
    QuoteLocation,
    QuoteSummary,
    QuoteView,
)
from veranico.modules.quoting.domain.fingerprint import fingerprint
from veranico.modules.quoting.domain.location import format_coordinates
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    ConflictError,
    IdempotencyConflictError,
    InvalidArgumentsError,
    NotFoundError,
)
from veranico.shared.kernel.ids import QuoteId, WorkspaceId, new_quote_id
from veranico.shared.kernel.principal import Principal


def idempotency_ref(workspace_id: WorkspaceId, key: str) -> str:
    """The document id of a key: keys of different workspaces never meet."""
    return hashlib.sha256(f"{workspace_id}:{key}".encode()).hexdigest()


def owned(quote: Quote | None, principal: Principal) -> Quote:
    """The quote when it belongs to the principal's workspace; otherwise `not_found`.

    A quote of another workspace answers exactly as a missing one, before any other check.
    """
    if quote is None or quote.workspace_id != principal.workspace_id:
        raise NotFoundError
    return quote


def key_id_of(principal: Principal) -> str | None:
    return principal.key_id if principal.kind == "api_key" else None


class QuoteService:
    def __init__(
        self,
        *,
        quotes: QuoteRepository,
        idempotency: IdempotencyStore,
        climate: ClimateFacade,
        pricing: PricingFacade,
        clock: Clock,
        new_id: Callable[[], QuoteId] = new_quote_id,
    ) -> None:
        self._quotes = quotes
        self._idempotency = idempotency
        self._climate = climate
        self._pricing = pricing
        self._clock = clock
        self._new_id = new_id

    async def create_quote(
        self, principal: Principal, command: CreateQuote, idempotency_key: str | None, actor: Actor
    ) -> QuoteView:
        ref: str | None = None
        quote_id = self._new_id()
        if idempotency_key is not None:
            ref = idempotency_ref(principal.workspace_id, idempotency_key)
            wanted = Reservation(principal.workspace_id, fingerprint(command), quote_id)
            reservation = await self._idempotency.reserve(ref, wanted, at=self._clock.now())
            if reservation.fingerprint != wanted.fingerprint:
                raise IdempotencyConflictError
            quote_id = reservation.quote_id
            stored = await self._quotes.get(quote_id)
            if stored is not None:
                return await self._replayed(stored, principal, ref)

        # Nothing is stored under the id yet: a new key, or a key whose first request died
        # before storing. Resolution is idempotent and pricing deterministic, so a
        # concurrent duplicate computes the same figures and `create` keeps one of them.
        request = command.location
        location = await self._climate.resolve_location(None, request.lat, request.lon)
        if not isinstance(location, Location):
            raise InvalidArgumentsError("the coordinates did not resolve to one location")
        dataset = await self._climate.ensure_history(request.lat, request.lon)
        priced = await self._pricing.price(dataset.dataset_id, command.cover, command.simulation)
        mutation = Quote.draft(
            quote_id=quote_id,
            workspace_id=principal.workspace_id,
            created_at=self._clock.now(),
            location=QuoteLocation(
                label=(
                    request.label
                    if request.label is not None
                    else format_coordinates(request.lat, request.lon)
                ),
                lat=request.lat,
                lon=request.lon,
                h3_cell=location.h3_cell,
                admin_region=(
                    request.admin_region
                    if request.admin_region is not None
                    else location.admin_region
                ),
            ),
            dataset_id=dataset.dataset_id,
            cover=command.cover,
            priced=priced,
            actor=actor,
            key_id=key_id_of(principal),
            idempotency_ref=ref,
        )
        try:
            await self._quotes.create(mutation)
        except QuoteAlreadyExistsError:
            return await self._replayed(await self._quotes.get(quote_id), principal, ref)
        return mutation.quote.view(list(mutation.audit))

    async def get_quote(self, principal: Principal, quote_id: QuoteId) -> QuoteView:
        quote = owned(await self._quotes.get(quote_id), principal)
        return quote.view(await self._quotes.audit(quote_id))

    async def list_quotes(self, principal: Principal) -> list[QuoteSummary]:
        quotes = await self._quotes.list_for_workspace(principal.workspace_id)
        return [
            QuoteSummary(
                quote_id=quote.quote_id,
                created_at=quote.created_at,
                status=quote.status,
                location_label=quote.location.label,
                premium=quote.priced.premium.premium,
            )
            for quote in sorted(quotes, key=lambda quote: quote.created_at, reverse=True)
            if quote.workspace_id == principal.workspace_id
        ]

    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None:
        entry = AuditEntry(at=self._clock.now(), actor=actor, action=action)

        def mutate(quote: Quote) -> Mutation:
            return Mutation(owned(quote, principal), (entry,))

        await self._quotes.update(quote_id, mutate)

    async def _replayed(
        self, stored: Quote | None, principal: Principal, ref: str | None
    ) -> QuoteView:
        """The quote already stored under a reserved id, only when this key created it."""
        if (
            stored is None
            or ref is None
            or stored.idempotency_ref != ref
            or stored.workspace_id != principal.workspace_id
        ):
            raise ConflictError("the quote id is taken by another quote")
        return stored.view(await self._quotes.audit(stored.quote_id))
