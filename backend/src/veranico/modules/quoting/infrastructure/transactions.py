"""Running a function in one Firestore transaction.

The client library's `async_transactional` begins the transaction, calls the function and
commits. A commit refused with `ABORTED` (contention) runs the function again, up to the
transaction's `max_attempts` (5 by default); after that it raises a `ValueError` whose
cause is the last `Aborted`. Reads come before writes. The function may therefore run more
than once and must have no side effect outside the transaction.

Production (Standard edition) serialises contenders with pessimistic locks, so a loser
normally waits and then sees the winner's state. The emulator does not: it refuses the
commit of every contender but one after a wait of about two seconds, so many contenders on
one document exhaust the attempts. Exhausted contention is answered as `conflict` (409):
nothing was written and the caller may repeat the request.

The library runs a refused transaction again at once, with no pause: it relies on the
server keeping the transaction's place in line. The emulator keeps no such order, so two
contenders that read the same document together block each other's commit until both time
out, both start again at the same instant and repeat that until both run out of attempts:
nobody wins, although only one of them had to lose. A later attempt therefore waits a
random time before its first read (full jitter, growing with the attempt), which lets one
contender read and commit while the other still holds no lock.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

from google.api_core.exceptions import Aborted
from google.cloud.firestore import AsyncClient, AsyncTransaction, async_transactional

from veranico.shared.kernel.errors import ConflictError

RETRY_JITTER_BASE_SECONDS = 0.1


async def run_in_transaction[T](
    client: AsyncClient,
    body: Callable[[AsyncTransaction], Awaitable[T]],
    *,
    jitter: Callable[[float, float], float] = random.uniform,
) -> T:
    attempts = 0

    async def attempt(transaction: AsyncTransaction) -> T:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            # Before any read, so the wait holds no lock.
            await asyncio.sleep(jitter(0.0, RETRY_JITTER_BASE_SECONDS * 2 ** (attempts - 1)))
        return await body(transaction)

    try:
        return await async_transactional(attempt)(client.transaction())
    except Aborted as error:
        raise ConflictError("too much contention on the document") from error
    except ValueError as error:
        if isinstance(error.__cause__, Aborted):
            raise ConflictError("too much contention on the document") from error
        raise
