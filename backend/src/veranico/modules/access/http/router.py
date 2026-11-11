"""Routes of `access`: API keys of a workspace and the visitor allowance.

Stub of the foundation milestone: path, method, operation id, security scheme and schemas
are final. Plan 07 replaces the handler bodies.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from veranico.modules.access.contracts import AccessFacade, Allowance, ApiKeyIssued, VisitorRef
from veranico.shared.infrastructure.http_auth import browser_principal, visitor_ref
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.principal import Principal

Browser = Annotated[Principal, Depends(browser_principal)]
Visitor = Annotated[VisitorRef, Depends(visitor_ref)]


def build_router(facade: AccessFacade) -> APIRouter:
    router = APIRouter(tags=["access"])

    @router.post("/workspace/api-keys", operation_id="issue_api_key")
    async def issue_api_key(principal: Browser) -> ApiKeyIssued:
        raise NotImplementedYetError

    @router.get("/allowance", operation_id="get_allowance")
    async def get_allowance(principal: Browser, visitor: Visitor) -> Allowance:
        raise NotImplementedYetError

    return router
