"""Public surface of `documents`: term sheets and evidence files of a quote."""

from typing import Literal, Protocol

from pydantic import BaseModel

from veranico.modules.quoting.contracts import Actor
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.principal import Principal


class DocumentRef(BaseModel, frozen=True):
    quote_id: QuoteId
    kind: Literal["term_sheet", "evidence"]
    locale: Locale | None
    content_type: str
    size_bytes: int
    path: str  # API path, never a bucket URL


class DocumentsFacade(Protocol):
    async def render_term_sheets(
        self, principal: Principal, quote_id: QuoteId, actor: Actor
    ) -> list[DocumentRef]: ...  # both locales; idempotent; audited
    async def term_sheet(
        self, principal: Principal, quote_id: QuoteId, locale: Locale
    ) -> bytes: ...  # renders when missing
    async def evidence(self, principal: Principal, quote_id: QuoteId) -> bytes: ...
