"""The API-role route of `carriers`: the delivery call. The mock carrier's route is in
`carrier_router.py`.

Path, method, operation id, security scheme and schemas are final since the foundation
milestone; only handler bodies change.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from veranico.modules.carriers.application.delivery_call import DeliveryCalls
from veranico.modules.carriers.contracts import DeliveryOutcome
from veranico.shared.infrastructure.http_auth import require_service_identity
from veranico.shared.kernel.errors import InvalidArgumentsError
from veranico.shared.kernel.ids import EventId

# The attempt headers of the delivery call. Both are trusted only because the route
# requires a service identity.
# Set by Cloud Tasks on every dispatch, 0 for the first; it also counts dispatches that
# failed before reaching the handler. The relay of development sends the same header.
# Source: https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks, read 2026-11-11.
RETRY_COUNT_HEADER = "X-CloudTasks-TaskRetryCount"
# Set by the dispatcher of `quoting`: the highest attempt number recorded before this
# delivery round. Absent means 0.
ATTEMPT_BASE_HEADER = "Veranico-Attempt-Base"


def build_router(calls: DeliveryCalls) -> APIRouter:
    """The API-role router. The attempt headers of the delivery call are read from the
    request and are not part of the OpenAPI document."""
    router = APIRouter(tags=["carriers"])

    @router.post(
        "/internal/outbox/{event_id}/deliver",
        operation_id="deliver_outbox_event",
        dependencies=[Depends(require_service_identity)],
        response_model=DeliveryOutcome,
    )
    async def deliver_outbox_event(
        event_id: EventId, request: Request
    ) -> DeliveryOutcome | JSONResponse:
        base = _count(request, ATTEMPT_BASE_HEADER)
        retry_count = _count(request, RETRY_COUNT_HEADER)
        result = await calls.handle_delivery_call(event_id, base, retry_count)
        if result.retry:
            # Any answer outside 2xx makes the queue call again; the body is the outcome.
            return JSONResponse(status_code=503, content=result.outcome.model_dump(mode="json"))
        return result.outcome

    return router


def _count(request: Request, header: str) -> int:
    """A non-negative integer header; absent means 0."""
    value = request.headers.get(header)
    if value is None:
        return 0
    if not (value.isascii() and value.isdigit()):
        raise InvalidArgumentsError
    return int(value)
