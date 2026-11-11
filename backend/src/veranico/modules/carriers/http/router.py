"""Routes of `carriers`: the delivery call (API role) and the mock carrier (carrier role).

Stub of the foundation milestone: path, method, operation id, security scheme and schemas
are final. Plan 04 replaces the handler bodies.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.security import APIKeyHeader

from veranico.modules.carriers.contracts import (
    CarriersFacade,
    DeliveryOutcome,
    Receipt,
    WebhookEnvelope,
)
from veranico.shared.infrastructure.http_auth import require_service_identity
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.ids import EventId

SIGNATURE_HEADER = "Veranico-Signature"
TIMESTAMP_HEADER = "Veranico-Timestamp"

# Describes the credential in OpenAPI only (`auto_error=False`): the handler verifies the
# signature over the raw body, so a missing or malformed header is its 401, not a 422.
_signature_scheme = APIKeyHeader(
    name=SIGNATURE_HEADER,
    scheme_name="WebhookSignature",
    description='`v1=<hex>`: HMAC SHA-256 of "<timestamp>.<raw body>" under the shared secret.',
    auto_error=False,
)


def build_router(facade: CarriersFacade) -> APIRouter:
    """The API-role router. The attempt headers of the delivery call are read from the
    request and are not part of the OpenAPI document."""
    router = APIRouter(tags=["carriers"])

    @router.post(
        "/internal/outbox/{event_id}/deliver",
        operation_id="deliver_outbox_event",
        dependencies=[Depends(require_service_identity)],
    )
    async def deliver_outbox_event(event_id: EventId) -> DeliveryOutcome:
        raise NotImplementedYetError

    return router


def build_carrier_router() -> APIRouter:
    """The carrier-role router, mounted at the root."""
    router = APIRouter(tags=["carrier"])

    @router.post("/carrier/v1/submissions", operation_id="receive_submission")
    async def receive_submission(
        envelope: WebhookEnvelope,
        signature: Annotated[str | None, Depends(_signature_scheme)],
        timestamp: Annotated[
            str | None, Header(alias=TIMESTAMP_HEADER, description="Unix seconds.")
        ] = None,
    ) -> Receipt:
        raise NotImplementedYetError

    return router
