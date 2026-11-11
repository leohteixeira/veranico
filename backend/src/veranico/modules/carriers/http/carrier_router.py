"""The route of the mock carrier (carrier role), mounted at the root.

Path, method, operation id, security scheme and schemas are final since the foundation
milestone. The signature must be checked over the raw received bytes before anything
parses them, while the route still declares its body model for OpenAPI. So the check runs
in the route class, ahead of FastAPI's own handling (the pattern of FastAPI's "Custom
Request and APIRoute class" guide): an unsigned request is answered 401 whatever its body,
and only then is the body parsed and validated (422 `invalid_arguments` when it fails).
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader

from veranico.modules.carriers.application.receive import Receiver
from veranico.modules.carriers.contracts import Receipt, WebhookEnvelope
from veranico.modules.carriers.domain.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER

# Describes the credential in OpenAPI only (`auto_error=False`): the route class verifies
# the signature over the raw body, so a missing or malformed header is its 401, not a 422.
_signature_scheme = APIKeyHeader(
    name=SIGNATURE_HEADER,
    scheme_name="WebhookSignature",
    description='`v1=<hex>`: HMAC SHA-256 of "<timestamp>.<raw body>" under the shared secret.',
    auto_error=False,
)


def _signed_route(receiver: Receiver) -> type[APIRoute]:
    class SignedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handle = super().get_route_handler()

            async def verify_then_handle(request: Request) -> Response:
                # Starlette keeps the bytes it read, so `handle` parses these same bytes.
                body = await request.body()
                receiver.authenticate(
                    request.headers.get(TIMESTAMP_HEADER),
                    request.headers.get(SIGNATURE_HEADER),
                    body,
                )
                return await handle(request)

            return verify_then_handle

    return SignedRoute


def build_carrier_router(receiver: Receiver) -> APIRouter:
    router = APIRouter(tags=["carrier"], route_class=_signed_route(receiver))

    @router.post("/carrier/v1/submissions", operation_id="receive_submission")
    async def receive_submission(
        envelope: WebhookEnvelope,
        # Declared for the OpenAPI document; both were verified by the route class.
        signature: Annotated[str | None, Depends(_signature_scheme)],
        timestamp: Annotated[
            str | None, Header(alias=TIMESTAMP_HEADER, description="Unix seconds.")
        ] = None,
    ) -> Receipt:
        return await receiver.receive(envelope)

    return router
