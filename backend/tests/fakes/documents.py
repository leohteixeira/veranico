"""In-memory fake of `DocumentsFacade`: references and bytes for quotes of the quoting facade
it was given. `calls` lists every call received, in order."""

from tests.fakes.access import Call
from veranico.modules.documents.contracts import DocumentRef
from veranico.modules.quoting.contracts import Actor, QuotingFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal

LOCALES: tuple[Locale, ...] = ("en", "pt-BR")


def term_sheet_bytes(quote_id: QuoteId, locale: Locale) -> bytes:
    return f"%PDF-fake term sheet {quote_id} {locale}".encode()


def evidence_bytes(quote_id: QuoteId) -> bytes:
    return f"fake-netcdf-evidence {quote_id}".encode()


class FakeDocumentsFacade:
    def __init__(self, quoting: QuotingFacade) -> None:
        self._quoting = quoting
        self._rendered: set[QuoteId] = set()
        self.calls: list[Call] = []

    async def render_term_sheets(
        self, principal: Principal, quote_id: QuoteId, actor: Actor
    ) -> list[DocumentRef]:
        self.calls.append(("render_term_sheets", (principal, quote_id, actor)))
        await self._quoting.get_quote(principal, quote_id)  # not_found for another workspace
        if quote_id not in self._rendered:
            self._rendered.add(quote_id)
            await self._quoting.append_audit(
                principal, quote_id, actor, Coded(code="audit.term_sheet_rendered")
            )
        return [
            DocumentRef(
                quote_id=quote_id,
                kind="term_sheet",
                locale=locale,
                content_type="application/pdf",
                size_bytes=len(term_sheet_bytes(quote_id, locale)),
                path=f"/api/v1/quotes/{quote_id}/term-sheet.pdf?lang={locale}",
            )
            for locale in LOCALES
        ]

    async def term_sheet(self, principal: Principal, quote_id: QuoteId, locale: Locale) -> bytes:
        self.calls.append(("term_sheet", (principal, quote_id, locale)))
        await self._quoting.get_quote(principal, quote_id)
        return term_sheet_bytes(quote_id, locale)

    async def evidence(self, principal: Principal, quote_id: QuoteId) -> bytes:
        self.calls.append(("evidence", (principal, quote_id)))
        await self._quoting.get_quote(principal, quote_id)
        return evidence_bytes(quote_id)
