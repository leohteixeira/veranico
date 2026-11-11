"""The text of the rendered term sheet (SPEC 8, 1, 4.4, 13), read back with pypdf.

Text extraction (plan 05, decision 4): the text of every page joined, runs of whitespace
collapsed to one space. The expected strings are the literals of `fixtures.py`.
"""

import io
import re
from collections.abc import Callable

import pytest
from pypdf import PdfReader

from tests.unit.documents import fixtures
from veranico.modules.documents.application.content import build_content
from veranico.modules.documents.application.i18n import en, pt_br
from veranico.modules.documents.infrastructure.pdf_renderer import ReportlabTermSheetRenderer
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.kernel.ids import Locale

LOCALES: tuple[Locale, ...] = ("en", "pt-BR")
CATALOGUES: dict[Locale, dict[str, str]] = {"en": en.CATALOGUE, "pt-BR": pt_br.CATALOGUE}
OTHER: dict[Locale, Locale] = {"en": "pt-BR", "pt-BR": "en"}
CASES = [
    (fixtures.rainfall_quote, fixtures.RAINFALL_ROWS, fixtures.RAINFALL_TEXTS),
    (fixtures.dry_spell_quote, fixtures.DRY_SPELL_ROWS, fixtures.DRY_SPELL_TEXTS),
]


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return " ".join(" ".join(page.extract_text() for page in reader.pages).split())


def rendered_text(quote: QuoteView, locale: Locale) -> str:
    return pdf_text(ReportlabTermSheetRenderer().render(build_content(quote), locale))


def has_phrase(text: str, phrase: str) -> bool:
    """True when the phrase is in the text as whole words (`Limit` is not in `Limite`)."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


@pytest.mark.req("R-8-1", "R-8-2", "R-13-3")
@pytest.mark.parametrize(("build", "rows", "texts"), CASES)
@pytest.mark.parametrize("locale", LOCALES)
def test_every_figure_is_on_the_page_next_to_its_label(
    build: Callable[[], QuoteView],
    rows: dict[Locale, tuple[str, ...]],
    texts: dict[Locale, tuple[str, ...]],
    locale: Locale,
) -> None:
    text = rendered_text(build(), locale)

    missing = [row for row in rows[locale] if not has_phrase(text, row)]
    assert missing == []


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize(("build", "rows", "texts"), CASES)
@pytest.mark.parametrize("locale", LOCALES)
def test_the_assumptions_and_the_data_source_are_on_the_page(
    build: Callable[[], QuoteView],
    rows: dict[Locale, tuple[str, ...]],
    texts: dict[Locale, tuple[str, ...]],
    locale: Locale,
) -> None:
    text = rendered_text(build(), locale)

    missing = [sentence for sentence in texts[locale] if sentence not in text]
    assert missing == []


@pytest.mark.req("R-1-1", "R-4.4-6")
@pytest.mark.parametrize("build", [fixtures.rainfall_quote, fixtures.dry_spell_quote])
@pytest.mark.parametrize("locale", LOCALES)
def test_the_disclaimer_and_the_attribution_are_on_the_page(
    build: Callable[[], QuoteView], locale: Locale
) -> None:
    text = rendered_text(build(), locale)

    assert fixtures.DISCLAIMER[locale] in text
    for sentence in fixtures.ATTRIBUTION[locale]:
        assert sentence in text, sentence


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("locale", LOCALES)
def test_the_warnings_are_on_the_page_only_when_the_quote_has_them(locale: Locale) -> None:
    with_warnings = rendered_text(fixtures.rainfall_quote(), locale)
    without = rendered_text(fixtures.dry_spell_quote(), locale)
    heading, trend, excluded = fixtures.RAINFALL_WARNINGS[locale]

    assert has_phrase(with_warnings, heading)
    assert trend in with_warnings
    assert excluded in with_warnings
    assert not has_phrase(without, heading)
    assert "5%" not in without  # the significance level appears only in the trend warning


@pytest.mark.parametrize("locale", LOCALES)
def test_only_a_quote_priced_on_synthetic_data_says_so(locale: Locale) -> None:
    """ADR 0017: synthetic figures are labelled; a real source is named as what it is."""
    notice = CATALOGUES[locale]["notice.synthetic"]

    assert notice in rendered_text(fixtures.dry_spell_quote(), locale)
    assert notice not in rendered_text(fixtures.rainfall_quote(), locale)


@pytest.mark.req("R-13-3")
@pytest.mark.parametrize("build", [fixtures.rainfall_quote, fixtures.dry_spell_quote])
@pytest.mark.parametrize("locale", LOCALES)
def test_a_page_holds_no_label_of_the_other_language(
    build: Callable[[], QuoteView], locale: Locale
) -> None:
    text = rendered_text(build(), locale)
    own, other = CATALOGUES[locale], CATALOGUES[OTHER[locale]]
    keys = [key for key in own if key.startswith(("label.", "section.", "title"))]
    differing = [key for key in keys if own[key] != other[key]]

    assert len(keys) - len(differing) == 2  # only Latitude and Longitude read the same
    assert [key for key in differing if has_phrase(text, other[key])] == []
    # ... and every label of its own language is there (the warnings only with a warning).
    absent = [key for key in keys if not has_phrase(text, own[key])]
    assert set(absent) <= {"section.warnings"}


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("locale", LOCALES)
def test_markup_characters_in_the_location_label_appear_literally(locale: Locale) -> None:
    quote = fixtures.dry_spell_quote()
    assert quote.location.label == "Talhão 7 <b>norte</b> & sul"

    assert "Talhão 7 <b>norte</b> & sul" in rendered_text(quote, locale)


def test_a_label_outside_the_font_encoding_still_renders() -> None:
    """Only text the user supplied can hold such characters; they are drawn as a box."""
    quote = fixtures.dry_spell_quote()
    location = quote.location.model_copy(update={"label": "Sítio Ővár 東京 fim"})

    text = rendered_text(quote.model_copy(update={"location": location}), "pt-BR")

    assert "Sítio" in text
    assert "fim" in text
    assert "Limite R$ 75.500,00" in text


@pytest.mark.parametrize(
    ("lat", "english", "portuguese"),
    [(0.00005, "Latitude 0.0001", "Latitude 0,0001"), (0.0, "Latitude 0.0000", "Latitude 0,0000")],
)
def test_a_point_on_the_equator_renders(lat: float, english: str, portuguese: str) -> None:
    """The equator crosses Brazil: a coordinate near zero must not fail the render."""
    quote = fixtures.rainfall_quote()
    location = quote.location.model_copy(update={"lat": lat})
    on_the_equator = quote.model_copy(update={"location": location})

    assert has_phrase(rendered_text(on_the_equator, "en"), english)
    assert has_phrase(rendered_text(on_the_equator, "pt-BR"), portuguese)


@pytest.mark.req("R-8-2")
def test_a_long_label_wraps_without_moving_a_figure() -> None:
    quote = fixtures.rainfall_quote()
    label = "Fazenda Santa Rita do Passa Quatro, gleba norte " * 6
    location = quote.location.model_copy(update={"label": label.strip()})

    text = rendered_text(quote.model_copy(update={"location": location}), "en")

    assert label.strip() in text
    assert [row for row in fixtures.RAINFALL_ROWS["en"][3:] if not has_phrase(text, row)] == []
