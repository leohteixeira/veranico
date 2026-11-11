"""Routes of `quoting`: quotes, submissions, approvals and the outbox sweep.

Stub of the foundation milestone: path, method, operation id, security scheme and schemas
are final. Plan 03 replaces the handler bodies.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path

from veranico.modules.quoting.contracts import (
    ApprovalView,
    CreateQuote,
    Decision,
    QuoteSummary,
    QuoteView,
    QuotingFacade,
    Submission,
)
from veranico.modules.quoting.http.schemas import SubmissionRequest, SweepResult
from veranico.shared.infrastructure.http_auth import (
    any_principal,
    api_key_principal,
    browser_principal,
    require_service_identity,
)
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.ids import QuoteId, SubmissionId
from veranico.shared.kernel.principal import Principal

Browser = Annotated[Principal, Depends(browser_principal)]
ApiKey = Annotated[Principal, Depends(api_key_principal)]
BrowserOrApiKey = Annotated[Principal, Depends(any_principal)]
QuoteIdPath = Annotated[QuoteId, Path(alias="id")]
ApprovalIdPath = Annotated[SubmissionId, Path(alias="id")]


def build_router(facade: QuotingFacade) -> APIRouter:
    router = APIRouter(tags=["quoting"])

    @router.post("/quotes", operation_id="create_quote")
    async def create_quote(
        principal: ApiKey,
        command: CreateQuote,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> QuoteView:
        raise NotImplementedYetError

    @router.get("/quotes", operation_id="list_quotes")
    async def list_quotes(principal: Browser) -> list[QuoteSummary]:
        raise NotImplementedYetError

    @router.get("/quotes/{id}", operation_id="get_quote")
    async def get_quote(principal: BrowserOrApiKey, quote_id: QuoteIdPath) -> QuoteView:
        raise NotImplementedYetError

    @router.post("/quotes/{id}/submissions", operation_id="request_submission")
    async def request_submission(
        principal: BrowserOrApiKey, quote_id: QuoteIdPath, request: SubmissionRequest
    ) -> Submission:
        raise NotImplementedYetError

    @router.get("/approvals", operation_id="list_approvals")
    async def list_approvals(
        principal: Browser,
        status: Literal["pending", "approved", "rejected"] | None = None,
    ) -> list[ApprovalView]:
        raise NotImplementedYetError

    @router.post("/approvals/{id}/decision", operation_id="decide_approval")
    async def decide_approval(
        principal: Browser, approval_id: ApprovalIdPath, decision: Decision
    ) -> ApprovalView:
        raise NotImplementedYetError

    @router.post("/approvals/{id}/redeliver", operation_id="redeliver_approval")
    async def redeliver_approval(principal: Browser, approval_id: ApprovalIdPath) -> ApprovalView:
        raise NotImplementedYetError

    @router.post(
        "/internal/outbox/sweep",
        operation_id="sweep_outbox",
        dependencies=[Depends(require_service_identity)],
    )
    async def sweep_outbox() -> SweepResult:
        raise NotImplementedYetError

    return router
