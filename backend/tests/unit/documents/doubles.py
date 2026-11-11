"""Test doubles of the `documents` tests: a counting renderer, a failing audit, the wiring."""

from dataclasses import replace

from tests.fakes.builders import daily_series
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.quoting import FakeQuotingFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.application.content import TermSheetContent, TextFigure
from veranico.modules.documents.application.evidence import Evidence
from veranico.modules.documents.application.facade import DocumentsService
from veranico.modules.documents.application.ports import TermSheetRenderer
from veranico.modules.documents.application.term_sheets import TermSheets
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.quoting.contracts import Actor, QuoteView, QuotingFacade
from veranico.shared.infrastructure.blobs import BlobStore
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale, QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal


def documents_facade(
    *,
    quoting: QuotingFacade,
    blobs: BlobStore,
    renderer: TermSheetRenderer,
    climate: ClimateFacade | None = None,
) -> DocumentsFacade:
    """The facade as `module.py` wires it, over the given collaborators."""
    return DocumentsService(
        term_sheets=TermSheets(quoting=quoting, blobs=blobs, renderer=renderer),
        evidence=Evidence(quoting=quoting, climate=climate or FakeClimateFacade(), blobs=blobs),
    )


def climate_with_dataset_of(quote: QuoteView) -> FakeClimateFacade:
    """A climate fake that knows the dataset of the quote (the fake refuses unknown ones)."""
    climate = FakeClimateFacade()
    series = daily_series(first_year=2020, last_year=2021)
    dataset = series.dataset.model_copy(update={"dataset_id": quote.dataset_id})
    climate.add_series(replace(series, dataset=dataset))
    return climate


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
