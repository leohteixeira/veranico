"""`DocumentsFacade` (contracts section 7): a thin front of the use cases."""

from veranico.modules.documents.application.evidence import Evidence
from veranico.modules.documents.application.term_sheets import TermSheets
from veranico.modules.documents.contracts import DocumentRef
from veranico.modules.quoting.contracts import Actor
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal


class DocumentsService:
    def __init__(self, *, term_sheets: TermSheets, evidence: Evidence) -> None:
        self._term_sheets = term_sheets
        self._evidence = evidence

    async def render_term_sheets(
        self, principal: Principal, quote_id: QuoteId, actor: Actor
    ) -> list[DocumentRef]:
        return await self._term_sheets.render_all(principal, quote_id, actor)

    async def term_sheet(self, principal: Principal, quote_id: QuoteId, locale: Locale) -> bytes:
        return await self._term_sheets.get(principal, quote_id, locale)

    async def evidence(self, principal: Principal, quote_id: QuoteId) -> bytes:
        return await self._evidence.get(principal, quote_id)
