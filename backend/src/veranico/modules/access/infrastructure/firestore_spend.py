"""`access_spend/day-{YYYY-MM-DD}` and `access_spend/month-{YYYY-MM}`: `cost_usd_micros`,
`calls`.

No expiry: these documents are the ledger and stay small.
"""

from google.cloud.firestore import AsyncClient, Increment

COLLECTION = "access_spend"
_COST = "cost_usd_micros"


class FirestoreSpendStore:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._collection = client.collection(COLLECTION)

    async def totals(self, day: str, month: str) -> tuple[int, int]:
        day_snapshot = await self._collection.document(f"day-{day}").get()
        month_snapshot = await self._collection.document(f"month-{month}").get()
        return (day_snapshot.to_dict() or {}).get(_COST, 0), (month_snapshot.to_dict() or {}).get(
            _COST, 0
        )

    async def add(self, day: str, month: str, cost_usd_micros: int) -> None:
        """One batched write with two increments.

        The total must be exact but is never refused at write time, and every visitor
        writes to the same two documents: increments need no read and no retry loop, and
        the batch applies both or neither. A merge creates a missing document and field.
        """
        batch = self._client.batch()
        for name in (f"day-{day}", f"month-{month}"):
            batch.set(
                self._collection.document(name),
                {_COST: Increment(cost_usd_micros), "calls": Increment(1)},
                merge=True,
            )
        await batch.commit()
