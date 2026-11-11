"""Firestore documents of `quoting` and the conversions to and from the domain.

The contract models are stored through their own JSON serialisation, so `Money` stays an
integer and `Rate` a string and nothing is rounded on the way. Bookkeeping times of the
outbox and every `expires_at` are native timestamps: the TTL policy needs a `Date and time`
value. TTL does not delete subcollections with their document, so audit entries carry their
own `expires_at`.
"""

from datetime import UTC, datetime
from typing import Any

from veranico.modules.quoting.contracts import AuditEntry, QuoteView, SubmissionApproved
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.domain.quote import Quote
from veranico.shared.kernel.ids import QuoteId

QUOTES = "quoting_quotes"
AUDIT = "audit"  # subcollection of a quote
IDEMPOTENCY = "quoting_idempotency"
OUTBOX = "quoting_outbox"


def quote_document(quote: Quote, expires_at: datetime) -> dict[str, Any]:
    document = quote.view([]).model_dump(mode="json")
    del document["audit"]  # the trail is the subcollection
    submission = quote.submission
    document["submission_id"] = submission.submission_id if submission is not None else None
    document["current_event_id"] = quote.current_event_id
    document["idempotency_ref"] = quote.idempotency_ref
    document["expires_at"] = expires_at
    return document


def quote_from_document(document: dict[str, Any]) -> Quote:
    view = QuoteView.model_validate({**_contract_fields(document, QuoteView), "audit": []})
    return Quote(
        quote_id=view.quote_id,
        workspace_id=view.workspace_id,
        created_at=view.created_at,
        status=view.status,
        location=view.location,
        dataset_id=view.dataset_id,
        cover=view.cover,
        priced=view.priced,
        submission=view.submission,
        current_event_id=document.get("current_event_id"),
        idempotency_ref=document.get("idempotency_ref"),
    )


def audit_document(entry: AuditEntry, seq: int, expires_at: datetime) -> dict[str, Any]:
    return {**entry.model_dump(mode="json"), "seq": seq, "expires_at": expires_at}


def audit_from_document(document: dict[str, Any]) -> AuditEntry:
    return AuditEntry.model_validate(_contract_fields(document, AuditEntry))


def outbox_document(record: OutboxRecord, expires_at: datetime) -> dict[str, Any]:
    return {
        "event": record.event.model_dump(mode="json"),
        "quote_id": record.quote_id,
        "status": record.status,
        "recorded_attempts": list(record.recorded_attempts),
        "attempt_base": record.attempt_base,
        "created_at": record.created_at,
        "enqueued_at": record.enqueued_at,
        "last_attempt_at": record.last_attempt_at,
        "next_attempt_at": record.next_attempt_at,
        "expires_at": expires_at,
    }


def outbox_from_document(document: dict[str, Any]) -> OutboxRecord:
    return OutboxRecord(
        event=SubmissionApproved.model_validate(document["event"]),
        quote_id=QuoteId(document["quote_id"]),
        status=document["status"],
        created_at=_plain(document["created_at"]),
        recorded_attempts=tuple(document["recorded_attempts"]),
        attempt_base=document["attempt_base"],
        enqueued_at=_optional(document["enqueued_at"]),
        last_attempt_at=_optional(document["last_attempt_at"]),
        next_attempt_at=_optional(document["next_attempt_at"]),
    )


def _contract_fields(
    document: dict[str, Any], model: type[QuoteView] | type[AuditEntry]
) -> dict[str, Any]:
    """Only the fields of the contract model: the document also holds lookup and TTL fields."""
    return {name: document[name] for name in model.model_fields if name in document}


def _optional(value: datetime | None) -> datetime | None:
    return None if value is None else _plain(value)


def _plain(value: datetime) -> datetime:
    """A timestamp read from Firestore as a plain UTC `datetime` (microsecond precision)."""
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=UTC,
    )
