"""`run_in_transaction` keeps a cancellation a cancellation.

The library rolls back on any exception; a task cancelled before `begin` has answered has
no transaction to roll back, and the rollback's `ValueError` used to replace the
`CancelledError`. The outbox relay, which survives ordinary errors, then kept running after
`stop()` and the stop waited forever (the 86-minute hang of the M3 gate).
"""

import asyncio

import pytest
from google.cloud.firestore import AsyncClient, AsyncTransaction

from veranico.modules.quoting.infrastructure.transactions import run_in_transaction

pytestmark = pytest.mark.integration


async def test_a_transaction_cancelled_before_begin_answers_raises_cancelled_error(
    firestore: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    begun = asyncio.Event()

    async def begin_that_never_answers(
        self: AsyncTransaction, retry_id: bytes | None = None
    ) -> None:
        begun.set()
        await asyncio.Event().wait()

    async def body(transaction: AsyncTransaction) -> None:
        pytest.fail("the body runs only after `begin` answered")

    monkeypatch.setattr(AsyncTransaction, "_begin", begin_that_never_answers)
    running = asyncio.create_task(run_in_transaction(firestore, body))
    await asyncio.wait_for(begun.wait(), timeout=5)

    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running
    assert running.cancelled()
