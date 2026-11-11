"""Routes of `documents`: the term sheet and the evidence file of a quote.

Both files are served from here and nowhere else: a response carries the bytes, never a
storage URL (SPEC 8). The handlers are thin mappings to the facade, which answers
`not_found` for a quote of another workspace.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.http.schemas import NetCdfResponse, PdfResponse
from veranico.shared.infrastructure.http_auth import any_principal
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal

BrowserOrApiKey = Annotated[Principal, Depends(any_principal)]
QuoteIdPath = Annotated[QuoteId, Path(alias="id")]

DEFAULT_LOCALE: Locale = "en"
_BY_PRIMARY_SUBTAG: dict[str, Locale] = {"en": "en", "pt": "pt-BR"}


def document_locale(lang: Locale | None, accept_language: str | None) -> Locale:
    """The language of a download.

    `?lang=` when present (the route's parameter type already refused any other value);
    otherwise the first language of `Accept-Language` that the term sheet exists in
    (`pt*` is `pt-BR`, `en*` is `en`), in the order the header lists them; otherwise `en`.
    """
    if lang is not None:
        return lang
    for item in (accept_language or "").split(","):
        tag = item.split(";", 1)[0].strip().lower()
        locale = _BY_PRIMARY_SUBTAG.get(tag.split("-", 1)[0])
        if locale is not None:
            return locale
    return DEFAULT_LOCALE


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def build_router(facade: DocumentsFacade) -> APIRouter:
    router = APIRouter(tags=["documents"])

    @router.get(
        "/quotes/{id}/term-sheet.pdf",
        operation_id="get_term_sheet",
        response_class=PdfResponse,
        response_model=None,
    )
    async def get_term_sheet(
        request: Request,
        principal: BrowserOrApiKey,
        quote_id: QuoteIdPath,
        lang: Locale | None = None,
    ) -> PdfResponse:
        locale = document_locale(lang, request.headers.get("Accept-Language"))
        data = await facade.term_sheet(principal, quote_id, locale)
        # The quote exists, so its id is one the service generated: safe in a header.
        return PdfResponse(
            data, headers=_attachment(f"veranico-{quote_id}-term-sheet-{locale}.pdf")
        )

    @router.get(
        "/quotes/{id}/evidence.nc",
        operation_id="get_evidence",
        response_class=NetCdfResponse,
        response_model=None,
    )
    async def get_evidence(principal: BrowserOrApiKey, quote_id: QuoteIdPath) -> NetCdfResponse:
        data = await facade.evidence(principal, quote_id)
        return NetCdfResponse(data, headers=_attachment(f"veranico-{quote_id}-evidence.nc"))

    return router
