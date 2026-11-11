"""Routes of `quoting`: quotes, submissions, approvals and the outbox sweep.

Thin mappings to the facade. The principal comes from `http_auth`; the audit actor follows
from its kind: a browser session is `human`, an API key is `api_client`.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path

from veranico.modules.quoting.contracts import (
    Actor,
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
from veranico.shared.kernel.errors import InvalidArgumentsError
from veranico.shared.kernel.ids import QuoteId, SubmissionId
from veranico.shared.kernel.principal import Principal

Browser = Annotated[Principal, Depends(browser_principal)]
ApiKey = Annotated[Principal, Depends(api_key_principal)]
BrowserOrApiKey = Annotated[Principal, Depends(any_principal)]
QuoteIdPath = Annotated[QuoteId, Path(alias="id")]
ApprovalIdPath = Annotated[SubmissionId, Path(alias="id")]


def _actor(principal: Principal) -> Actor:
    return "human" if principal.kind == "browser" else "api_client"


def build_router(facade: QuotingFacade, *, sweep_age_seconds: int) -> APIRouter:
    router = APIRouter(tags=["quoting"])

    @router.post("/quotes", operation_id="create_quote")
    async def create_quote(
        principal: ApiKey,
        command: CreateQuote,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> QuoteView:
        if not idempotency_key.strip():
            raise InvalidArgumentsError("the Idempotency-Key header is empty")
        return await facade.create_quote(principal, command, idempotency_key, _actor(principal))

    @router.get("/quotes", operation_id="list_quotes")
    async def list_quotes(principal: Browser) -> list[QuoteSummary]:
        return await facade.list_quotes(principal)

    @router.get("/quotes/{id}", operation_id="get_quote")
    async def get_quote(principal: BrowserOrApiKey, quote_id: QuoteIdPath) -> QuoteView:
        return await facade.get_quote(principal, quote_id)

    @router.post("/quotes/{id}/submissions", operation_id="request_submission")
    async def request_submission(
        principal: BrowserOrApiKey, quote_id: QuoteIdPath, request: SubmissionRequest
    ) -> Submission:
        return await facade.request_submission(
            principal, quote_id, request.carrier_id, _actor(principal)
        )

    @router.get("/approvals", operation_id="list_approvals")
    async def list_approvals(
        principal: Browser,
        status: Literal["pending", "approved", "rejected"] | None = None,
    ) -> list[ApprovalView]:
        return await facade.list_approvals(principal, status)

    @router.post("/approvals/{id}/decision", operation_id="decide_approval")
    async def decide_approval(
        principal: Browser, approval_id: ApprovalIdPath, decision: Decision
    ) -> ApprovalView:
        return await facade.decide(principal, approval_id, decision)

    @router.post("/approvals/{id}/redeliver", operation_id="redeliver_approval")
    async def redeliver_approval(principal: Browser, approval_id: ApprovalIdPath) -> ApprovalView:
        return await facade.redeliver(principal, approval_id)

    @router.post(
        "/internal/outbox/sweep",
        operation_id="sweep_outbox",
        dependencies=[Depends(require_service_identity)],
    )
    async def sweep_outbox() -> SweepResult:
        return SweepResult(enqueued=await facade.sweep_outbox(sweep_age_seconds))

    return router
