"""Routes of `documents`: the term sheet and the evidence file of a quote.

Stub of the foundation milestone: path, method, operation id, security scheme, query
parameter and media types are final. Plan 05 replaces the handler bodies.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.http.schemas import NetCdfResponse, PdfResponse
from veranico.shared.infrastructure.http_auth import any_principal
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal

BrowserOrApiKey = Annotated[Principal, Depends(any_principal)]
QuoteIdPath = Annotated[QuoteId, Path(alias="id")]


def build_router(facade: DocumentsFacade) -> APIRouter:
    router = APIRouter(tags=["documents"])

    @router.get(
        "/quotes/{id}/term-sheet.pdf",
        operation_id="get_term_sheet",
        response_class=PdfResponse,
        response_model=None,
    )
    async def get_term_sheet(
        principal: BrowserOrApiKey, quote_id: QuoteIdPath, lang: Locale | None = None
    ) -> PdfResponse:
        raise NotImplementedYetError

    @router.get(
        "/quotes/{id}/evidence.nc",
        operation_id="get_evidence",
        response_class=NetCdfResponse,
        response_model=None,
    )
    async def get_evidence(principal: BrowserOrApiKey, quote_id: QuoteIdPath) -> NetCdfResponse:
        raise NotImplementedYetError

    return router
