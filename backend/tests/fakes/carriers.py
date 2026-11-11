"""In-memory fake of `CarriersFacade`: a fixed catalogue and scripted delivery outcomes.

`script("retryable", "delivered")` sets what the next calls of `deliver` return, in order;
an unscripted call delivers. Every attempt is recorded through the quoting facade the fake
was given, as the real module does. `calls` lists every call received, in order.
"""

from collections.abc import Sequence
from typing import Literal

from tests.fakes import builders
from tests.fakes.access import Call
from veranico.modules.carriers.contracts import DeliveryOutcome
from veranico.modules.quoting.contracts import (
    CarrierCatalog,
    CarrierInfo,
    DeliveryAttempt,
    QuotingFacade,
)
from veranico.shared.kernel.ids import EventId

Outcome = Literal["delivered", "retryable", "permanent"]


class FakeCarrierCatalog:
    def __init__(self, carriers: Sequence[CarrierInfo] = builders.CARRIERS) -> None:
        self._carriers = {carrier.carrier_id: carrier for carrier in carriers}

    def get(self, carrier_id: str) -> CarrierInfo | None:
        return self._carriers.get(carrier_id)

    def all(self) -> list[CarrierInfo]:
        return list(self._carriers.values())


class FakeCarriersFacade:
    def __init__(
        self, quoting: QuotingFacade, *, carriers: Sequence[CarrierInfo] = builders.CARRIERS
    ) -> None:
        self._quoting = quoting
        self._catalog = FakeCarrierCatalog(carriers)
        self._script: list[Outcome] = []
        self._receipts = 0
        self.calls: list[Call] = []

    def script(self, *outcomes: Outcome) -> None:
        """Set the outcomes of the next deliveries, in order."""
        self._script = list(outcomes)

    def catalog(self) -> CarrierCatalog:
        self.calls.append(("catalog", ()))
        return self._catalog

    async def deliver(self, event_id: EventId, attempt: int) -> DeliveryOutcome:
        self.calls.append(("deliver", (event_id, attempt)))
        await self._quoting.load_event(event_id)  # raises not_found for an unknown event
        outcome: Outcome = self._script.pop(0) if self._script else "delivered"
        receipt_id = None
        if outcome == "delivered":
            self._receipts += 1
            receipt_id = f"R-{self._receipts:06d}"
        recorded = DeliveryAttempt(
            event_id=event_id,
            attempt=attempt,
            status_code={"delivered": 200, "retryable": 503, "permanent": 400}[outcome],
            error_code=None if outcome == "delivered" else "delivery_failed",
            duration_ms=1,
            receipt_id=receipt_id,
        )
        await self._quoting.record_delivery_attempt(recorded)
        return DeliveryOutcome(
            delivered=outcome == "delivered", retryable=outcome == "retryable", attempt=recorded
        )
