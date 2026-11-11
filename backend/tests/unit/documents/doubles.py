"""Test doubles of the `documents` unit tests: a counting renderer and a failing audit."""

from tests.fakes.quoting import FakeQuotingFacade
from veranico.modules.documents.application.content import TermSheetContent, TextFigure
from veranico.modules.quoting.contracts import Actor
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale, QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal


def browser(workspace_id: str) -> Principal:
    return Principal(workspace_id=WorkspaceId(workspace_id), kind="browser")


def api_key(workspace_id: str) -> Principal:
    return Principal(workspace_id=WorkspaceId(workspace_id), kind="api_key", key_id="key-1")


class CountingRenderer:
    """Implements `TermSheetRenderer`: deterministic bytes, and the list of renders asked."""

    def __init__(self) -> None:
        self.renders: list[tuple[str, Locale]] = []

    def render(self, content: TermSheetContent, locale: Locale) -> bytes:
        quote_id = content.sections[0].rows[0].value
        assert isinstance(quote_id, TextFigure)
        self.renders.append((quote_id.text, locale))
        return f"%PDF-counting {quote_id.text} {locale}".encode()


class AuditFailsQuoting(FakeQuotingFacade):
    """A quoting facade whose `append_audit` fails, as when Firestore is unavailable."""

    async def append_audit(
        self, principal: Principal, quote_id: QuoteId, actor: Actor, action: Coded
    ) -> None:
        self.calls.append(("append_audit", (principal, quote_id, actor, action)))
        raise RuntimeError("audit store unavailable")
