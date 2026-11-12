"""Rendering is deterministic for a given quote (SPEC 8) and the result is a PDF."""

import io
import time
from collections.abc import Callable

import pytest
from pypdf import PdfReader

from tests.unit.documents import fixtures
from veranico.modules.documents.application.content import build_content
from veranico.modules.documents.application.ports import TermSheetRenderer
from veranico.modules.documents.infrastructure.pdf_renderer import ReportlabTermSheetRenderer
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.kernel.ids import Locale

LOCALES: tuple[Locale, ...] = ("en", "pt-BR")
BUILDERS = [fixtures.rainfall_quote, fixtures.dry_spell_quote]
THREE_DAYS = 3 * 24 * 60 * 60


def render(quote: QuoteView, locale: Locale) -> bytes:
    renderer: TermSheetRenderer = ReportlabTermSheetRenderer()  # the adapter satisfies the port
    return renderer.render(build_content(quote), locale)


@pytest.mark.req("R-8-3")
@pytest.mark.parametrize("build", BUILDERS)
@pytest.mark.parametrize("locale", LOCALES)
def test_two_renders_of_one_quote_are_identical_even_days_apart(
    build: Callable[[], QuoteView], locale: Locale, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clock moves between the renders: a creation timestamp in the file would show."""
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    first = render(build(), locale)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + THREE_DAYS)

    second = render(build(), locale)

    assert second == first


@pytest.mark.req("R-8-3")
def test_the_file_carries_no_date_of_the_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    data = render(fixtures.rainfall_quote(), "en")

    metadata = PdfReader(io.BytesIO(data)).metadata

    assert metadata is not None
    assert metadata["/CreationDate"] == "D:20000101000000+00'00'"  # reportlab's invariant date
    assert metadata["/ModDate"] == metadata["/CreationDate"]
    assert metadata.title == "Parametric rainfall cover: indicative term sheet"


@pytest.mark.req("R-8-3")
def test_the_page_does_not_change_with_the_status_of_the_quote() -> None:
    quote = fixtures.rainfall_quote()
    submitted = quote.model_copy(update={"status": "submitted", "audit": []})

    assert render(submitted, "pt-BR") == render(quote, "pt-BR")


@pytest.mark.req("R-8-1", "R-13-3")
@pytest.mark.parametrize("build", BUILDERS)
def test_each_language_is_its_own_pdf_with_at_least_one_page(
    build: Callable[[], QuoteView],
) -> None:
    english, portuguese = render(build(), "en"), render(build(), "pt-BR")

    assert english != portuguese
    for data in (english, portuguese):
        assert data.startswith(b"%PDF-")
        assert len(PdfReader(io.BytesIO(data)).pages) >= 1


@pytest.mark.req("R-8-3")
def test_different_quotes_give_different_files() -> None:
    assert render(fixtures.rainfall_quote(), "en") != render(fixtures.dry_spell_quote(), "en")
