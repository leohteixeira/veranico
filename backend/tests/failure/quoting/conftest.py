"""The `quoting` failure campaign: the real module over HTTP on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/failure/quoting -m failure -q

The application is the one of `tests/api/quoting` (this module's router, fakes for the
other modules, a dispatcher that only records). Outcomes are asserted, never timing. The
emulator is shared: every workspace id is random, its documents are deleted afterwards and
the clock stands decades in the past, so a sweep here never touches another run's records.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from google.cloud.firestore_v1.base_query import FieldFilter

from tests.api.quoting.conftest import (
    INTERNAL_TOKEN,
    V1,
    QuotingApi,
    Session,
    build_api,
    quote_body,
)
from veranico.modules.quoting.infrastructure.mapping import IDEMPOTENCY, OUTBOX, QUOTES

SWEEP = f"{V1}/internal/outbox/sweep"
SERVICE = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
DECISIONS = ("audit.approved", "audit.rejected")


@pytest.fixture
async def api() -> AsyncIterator[QuotingApi]:
    context = build_api()
    yield context
    await context.close()


async def pending(session: Session, key: str = "request-1") -> tuple[str, str]:
    """A quote with a requested submission: its quote id and its approval id."""
    quote = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": key}
    )
    assert quote.status_code == 200
    submission = await session.api.post(
        f"{V1}/quotes/{quote.json()['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
    )
    assert submission.status_code == 200
    return quote.json()["quote_id"], submission.json()["submission_id"]


async def decide(session: Session, approval_id: str, approve: bool) -> httpx.Response:
    return await session.browser.post(
        f"{V1}/approvals/{approval_id}/decision", json={"approve": approve}
    )


async def quote_of(session: Session, quote_id: str) -> dict[str, Any]:
    response = await session.browser.get(f"{V1}/quotes/{quote_id}")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def approval_of(session: Session, approval_id: str) -> dict[str, Any]:
    """The approval as `GET /approvals` shows it (the call also runs the sweep)."""
    response = await session.browser.get(f"{V1}/approvals")
    assert response.status_code == 200
    (approval,) = [a for a in response.json() if a["approval_id"] == approval_id]
    found: dict[str, Any] = approval
    return found


def audit_codes(quote: dict[str, Any]) -> list[str]:
    return [entry["action"]["code"] for entry in quote["audit"]]


async def outbox_statuses(api: QuotingApi, quote_id: str) -> list[str]:
    """The status of every outbox document of one quote."""
    query = api.firestore.collection(OUTBOX).where(filter=FieldFilter("quote_id", "==", quote_id))
    return [snapshot.get("status") async for snapshot in query.stream()]


async def stored_quotes(api: QuotingApi, workspace_id: str) -> list[str]:
    query = api.firestore.collection(QUOTES).where(
        filter=FieldFilter("workspace_id", "==", workspace_id)
    )
    return [snapshot.id async for snapshot in query.stream()]


async def stored_keys(api: QuotingApi, workspace_id: str) -> list[str]:
    query = api.firestore.collection(IDEMPOTENCY).where(
        filter=FieldFilter("workspace_id", "==", workspace_id)
    )
    return [snapshot.id async for snapshot in query.stream()]
