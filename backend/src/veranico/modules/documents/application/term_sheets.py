"""Term sheets of a quote: render what is missing, store it, record the audit entry.

Order inside one render: `get_quote` (which answers `not_found` for another workspace),
read the stored blob, render, store, `append_audit`.

* A quote's priced content never changes and the page shows no status, so a stored term
  sheet is returned as it is for the life of the quote.
* The blob is written create-only. When two first renders race, both produce the same bytes
  (rendering is deterministic), one write wins and only the winner records the audit entry.
* A failed `append_audit` after a successful write is logged and does not fail the call:
  the document exists and the next call finds it.
* The path is built from the workspace of the stored quote, never from the request.
"""

import logging

from veranico.modules.documents.application.content import build_content
from veranico.modules.documents.application.ports import TermSheetRenderer
from veranico.modules.documents.contracts import DocumentRef
from veranico.modules.quoting.contracts import Actor, QuoteView, QuotingFacade
from veranico.shared.infrastructure.blobs import (
    BlobNotFoundError,
    BlobPreconditionError,
    BlobStore,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal

logger = logging.getLogger(__name__)

LOCALES: tuple[Locale, ...] = ("en", "pt-BR")
PDF_CONTENT_TYPE = "application/pdf"
RENDERED_ACTION = "audit.term_sheet_rendered"
# Who rendered, when a download finds no stored term sheet (plan 05, decision 8).
_DOWNLOAD_ACTOR: dict[str, Actor] = {
    "browser": "human",
    "api_key": "api_client",
    "system": "system",
}


def document_prefix(quote: QuoteView) -> str:
    """`documents/<workspace_id>/<quote_id>/`: the quote's own workspace, not the caller's."""
    return f"documents/{quote.workspace_id}/{quote.quote_id}/"


def term_sheet_blob_path(quote: QuoteView, locale: Locale) -> str:
    return f"{document_prefix(quote)}term-sheet.{locale}.pdf"


def term_sheet_api_path(quote_id: QuoteId, locale: Locale) -> str:
    return f"/api/v1/quotes/{quote_id}/term-sheet.pdf?lang={locale}"


class TermSheets:
    def __init__(
        self, *, quoting: QuotingFacade, blobs: BlobStore, renderer: TermSheetRenderer
    ) -> None:
        self._quoting = quoting
        self._blobs = blobs
        self._renderer = renderer

    async def render_all(
        self, principal: Principal, quote_id: QuoteId, actor: Actor
    ) -> list[DocumentRef]:
        """Both locales, rendering only what is not stored yet."""
        quote = await self._quoting.get_quote(principal, quote_id)
        references = []
        for locale in LOCALES:
            data = await self._ensure(principal, quote, locale, actor)
            references.append(
                DocumentRef(
                    quote_id=quote.quote_id,
                    kind="term_sheet",
                    locale=locale,
                    content_type=PDF_CONTENT_TYPE,
                    size_bytes=len(data),
                    path=term_sheet_api_path(quote.quote_id, locale),
                )
            )
        return references

    async def get(self, principal: Principal, quote_id: QuoteId, locale: Locale) -> bytes:
        """The term sheet of one locale, rendered now when it is not stored yet."""
        quote = await self._quoting.get_quote(principal, quote_id)
        return await self._ensure(principal, quote, locale, _DOWNLOAD_ACTOR[principal.kind])

    async def _ensure(
        self, principal: Principal, quote: QuoteView, locale: Locale, actor: Actor
    ) -> bytes:
        path = term_sheet_blob_path(quote, locale)
        try:
            return (await self._blobs.get(path)).data
        except BlobNotFoundError:
            pass
        data = self._renderer.render(build_content(quote), locale)
        try:
            await self._blobs.put(path, data, content_type=PDF_CONTENT_TYPE, if_generation_match=0)
        except BlobPreconditionError:
            # A concurrent render stored the same document first, and records the entry.
            return (await self._blobs.get(path)).data
        await self._record(principal, quote.quote_id, locale, actor)
        return data

    async def _record(
        self, principal: Principal, quote_id: QuoteId, locale: Locale, actor: Actor
    ) -> None:
        action = Coded(code=RENDERED_ACTION, params={"locale": locale})
        try:
            await self._quoting.append_audit(principal, quote_id, actor, action)
        except Exception:
            # The document is stored and the next call returns it; only the entry is missing.
            logger.exception(
                "term sheet %s (%s) stored, but its audit entry was not recorded", quote_id, locale
            )
