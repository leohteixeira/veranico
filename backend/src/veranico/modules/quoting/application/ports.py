"""Persistence ports of `quoting`, implemented in `quoting/infrastructure`.

The functions passed to `update` and `update_for_event` must be pure: an adapter runs them
inside a transaction and may run them more than once.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from veranico.modules.quoting.contracts import AuditEntry
from veranico.modules.quoting.domain.outbox import OutboxRecord, OutboxStatus
from veranico.modules.quoting.domain.quote import Mutation, Quote
from veranico.shared.kernel.ids import EventId, QuoteId, SubmissionId, WorkspaceId


class QuoteAlreadyExistsError(Exception):
    """`QuoteRepository.create` found a quote under the same id; nothing was written."""


@dataclass(frozen=True, slots=True)
class Reservation:
    """An idempotency key bound to the fingerprint of its command and to one quote id."""

    workspace_id: WorkspaceId
    fingerprint: str
    quote_id: QuoteId


class QuoteRepository(Protocol):
    async def create(self, mutation: Mutation) -> None:
        """Store a new quote with its audit entries, atomically.

        Raises `QuoteAlreadyExistsError` when the id is taken; it never overwrites.
        """
        ...

    async def get(self, quote_id: QuoteId) -> Quote | None: ...

    async def audit(self, quote_id: QuoteId) -> list[AuditEntry]:
        """The audit trail, oldest first; entries of one mutation keep their order."""
        ...

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> list[Quote]: ...

    async def find_by_submission(self, submission_id: SubmissionId) -> Quote | None: ...

    async def update(self, quote_id: QuoteId, mutate: Callable[[Quote], Mutation]) -> Mutation:
        """Read the quote, apply `mutate` and write its whole result in one transaction.

        Raises `not_found` when the quote does not exist. An error raised by `mutate`
        leaves everything unchanged and propagates.
        """
        ...

    async def update_for_event(
        self, event_id: EventId, mutate: Callable[[Quote, OutboxRecord], Mutation]
    ) -> Mutation:
        """As `update`, reading the outbox record and its quote in the same transaction.

        Raises `not_found` when the event does not exist.
        """
        ...


class IdempotencyStore(Protocol):
    async def reserve(self, ref: str, wanted: Reservation, *, at: datetime) -> Reservation:
        """Atomically create the reservation under `ref`, or return the one already there."""
        ...


class OutboxStore(Protocol):
    async def get(self, event_id: EventId) -> OutboxRecord | None: ...

    async def list_by_status(self, status: OutboxStatus) -> list[OutboxRecord]: ...

    async def mark_enqueued(self, event_id: EventId, at: datetime) -> None:
        """Move a `pending` record to `enqueued`; any other record is left as it is."""
        ...

    async def record_dispatch(self, event_id: EventId, next_attempt_at: datetime) -> None:
        """Relay only: count one call of the deliver endpoint and store when the next is due.

        A delivered or abandoned record is left as it is.
        """
        ...
