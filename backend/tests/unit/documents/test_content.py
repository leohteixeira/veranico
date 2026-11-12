"""`build_content`: the figures of a quote, unchanged and untranslated (SPEC 8)."""

from dataclasses import fields, is_dataclass
from typing import Any

import pytest

from tests.unit.documents.fixtures import dry_spell_quote, rainfall_quote
from veranico.modules.documents.application.content import (
    CodedFigure,
    CoordinateFigure,
    CountFigure,
    DateFigure,
    PercentFigure,
    QuantityFigure,
    RateFigure,
    Row,
    Section,
    TermSheetContent,
    TextFigure,
    WindowFigure,
    build_content,
)
from veranico.modules.documents.application.i18n import en, pt_br
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.kernel.coded import Coded

# Plan 05, decision 2: the figures of the term sheet, by the label of their row.
FIGURE_LABELS = {
    "quote_id",
    "created_at",
    "location",
    "latitude",
    "longitude",
    "admin_region",
    "dataset_id",
    "index_type",
    "window",
    "trigger",
    "exit",
    "limit",
    "seasons_used",
    "seasons_excluded",
    "trigger_frequency",
    "burn_cost",
    "max_payout",
    "max_payout_season",
    "trend_slope",
    "trend_p_value",
    "method",
    "n",
    "seed",
    "expected_loss",
    "std_dev",
    "probability_of_payout",
    "payout_1_in_10",
    "payout_1_in_100",
    "gap_to_burn_cost",
    "premium",
    "rate_on_line",
    "risk_load",
    "expense_load",
}


def all_rows(content: TermSheetContent) -> list[Row]:
    return [row for section in content.sections for row in section.rows]


def figures(content: TermSheetContent) -> dict[str, Any]:
    return {row.label.code.removeprefix("label."): row.value for row in all_rows(content)}


def section(content: TermSheetContent, name: str) -> Section:
    (found,) = [item for item in content.sections if item.title.code == f"section.{name}"]
    return found


def walk(value: Any) -> list[Any]:
    """Every object reachable through the dataclasses and tuples of the content."""
    if is_dataclass(value) and not isinstance(value, type):
        return [value] + [
            item for field in fields(value) for item in walk(getattr(value, field.name))
        ]
    if isinstance(value, tuple):
        return [item for element in value for item in walk(element)]
    return [value]


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("build", [rainfall_quote, dry_spell_quote])
def test_every_figure_of_the_term_sheet_appears_once(build: Any) -> None:
    labels = [row.label.code for row in all_rows(build_content(build()))]

    assert sorted(labels) == sorted(f"label.{name}" for name in FIGURE_LABELS)


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("build", [rainfall_quote, dry_spell_quote])
def test_each_figure_is_the_value_object_of_the_quote_unchanged(build: Any) -> None:
    quote: QuoteView = build()
    backtest, simulation, premium = (
        quote.priced.backtest,
        quote.priced.simulation,
        quote.priced.premium,
    )
    index = quote.cover.index

    found = figures(build_content(quote))

    # Money: the very `Money` object of the quote, never a copy made from a number.
    assert found["limit"].money is quote.cover.limit
    assert found["burn_cost"].money is backtest.burn_cost
    assert found["max_payout"].money is backtest.max_payout
    assert found["expected_loss"].money is simulation.expected_loss
    assert found["std_dev"].money is simulation.std_dev
    assert found["payout_1_in_10"].money is simulation.payout_1_in_10
    assert found["payout_1_in_100"].money is simulation.payout_1_in_100
    assert found["gap_to_burn_cost"].money is simulation.gap_to_burn_cost
    assert found["premium"].money is premium.premium
    # Rates: the stored six-place strings.
    assert found["trigger_frequency"] == PercentFigure(backtest.trigger_frequency)
    assert found["probability_of_payout"] == PercentFigure(simulation.probability_of_payout)
    assert found["rate_on_line"] == PercentFigure(premium.rate_on_line)
    assert found["risk_load"] == PercentFigure(premium.risk_load)
    assert found["expense_load"] == PercentFigure(premium.expense_load)
    assert found["trend_p_value"] == RateFigure(backtest.trend.p_value)
    # Quantities, counts, dates and identifiers.
    days = index.index_type == "dry_spell_above"
    unit = "unit.days" if days else "unit.mm"
    assert found["trigger"] == QuantityFigure(index.trigger, unit)
    assert found["exit"] == QuantityFigure(index.exit, unit)
    assert found["trend_slope"] == QuantityFigure(
        backtest.trend.slope_per_decade, f"{unit}_per_decade"
    )
    assert found["latitude"] == CoordinateFigure(quote.location.lat)
    assert found["longitude"] == CoordinateFigure(quote.location.lon)
    assert found["window"] == WindowFigure(index.window.start, index.window.end)
    assert found["seasons_used"] == CountFigure(backtest.seasons_used)
    assert found["seasons_excluded"] == CountFigure(len(backtest.seasons_excluded))
    assert found["max_payout_season"] == CountFigure(backtest.max_payout_season)  # type: ignore[arg-type]  # not None in the fixtures
    assert found["n"] == CountFigure(simulation.n)
    assert found["seed"] == CountFigure(simulation.seed)
    assert found["created_at"] == DateFigure(quote.created_at)
    assert found["quote_id"] == TextFigure(quote.quote_id)
    assert found["location"] == TextFigure(quote.location.label)
    # The dataset by its kind in words, as the Quote tab names it, never the raw id.
    kind = quote.dataset_id.split(":", 1)[0]
    assert kind in {"cube", "point"}
    assert found["dataset_id"] == CodedFigure(Coded(code=f"dataset.{kind}"))
    assert found["index_type"] == CodedFigure(Coded(code=f"index_type.{index.index_type}"))
    assert found["method"] == CodedFigure(Coded(code=f"method.{simulation.method}"))


@pytest.mark.req("R-8-2")
def test_a_missing_region_or_payout_season_is_named_not_available() -> None:
    quote = dry_spell_quote()  # no administrative region
    backtest = quote.priced.backtest.model_copy(update={"max_payout_season": None})
    priced = quote.priced.model_copy(update={"backtest": backtest})

    found = figures(build_content(quote.model_copy(update={"priced": priced})))

    assert found["admin_region"] == CodedFigure(Coded(code="value.not_available"))
    assert found["max_payout_season"] == CodedFigure(Coded(code="value.not_available"))
    assert figures(build_content(rainfall_quote()))["admin_region"] == TextFigure("Minas Gerais")


@pytest.mark.req("R-8-2")
def test_the_warnings_section_holds_one_text_per_warning_of_the_backtest() -> None:
    quote = rainfall_quote()

    warnings = section(build_content(quote), "warnings")

    assert warnings.rows == ()
    assert [coded.code for coded in warnings.paragraphs] == [
        "warning.trend_significant",
        "warning.seasons_excluded",
    ]
    assert all(
        shown is stored
        for shown, stored in zip(warnings.paragraphs, quote.priced.backtest.warnings, strict=True)
    )


@pytest.mark.req("R-8-2")
def test_there_is_no_warnings_section_without_a_warning() -> None:
    titles = [item.title.code for item in build_content(dry_spell_quote()).sections]

    assert "section.warnings" not in titles
    assert titles == [
        "section.quote",
        "section.cover",
        "section.premium",
        "section.backtest",
        "section.simulation",
        "section.assumptions",
        "section.data",
        "section.disclaimer",
    ]


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("build", [rainfall_quote, dry_spell_quote])
def test_the_assumptions_keep_their_order(build: Any) -> None:
    quote: QuoteView = build()

    assumptions = section(build_content(quote), "assumptions")

    assert list(assumptions.paragraphs) == quote.priced.assumptions
    assert [coded.code for coded in assumptions.paragraphs] == [
        "assumption.index_type",
        "assumption.window",
        "assumption.seasons_used",
        "assumption.simulation_method",
        "assumption.loads",
        "assumption.data_source",
    ]


@pytest.mark.req("R-1-1", "R-4.4-6")
def test_the_attribution_and_the_disclaimer_close_the_term_sheet() -> None:
    content = build_content(rainfall_quote())

    assert section(content, "data").paragraphs == (
        Coded(code="attribution", params={"year": 2026}),  # the year the quote was created
    )
    assert section(content, "disclaimer").paragraphs == (Coded(code="disclaimer"),)
    assert content.sections[-1].title.code == "section.disclaimer"


def test_a_quote_priced_on_synthetic_data_carries_the_synthetic_notice() -> None:
    """ADR 0017: synthetic figures are never presented as real weather history."""
    assert build_content(dry_spell_quote()).notices == (Coded(code="notice.synthetic"),)
    assert build_content(rainfall_quote()).notices == ()


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("build", [rainfall_quote, dry_spell_quote])
def test_the_content_holds_no_translated_text_and_no_formatted_number(build: Any) -> None:
    quote: QuoteView = build()
    literal = {quote.quote_id, quote.location.label, quote.location.admin_region}
    window = {quote.cover.index.window.start, quote.cover.index.window.end}
    rates = {
        quote.priced.backtest.trigger_frequency,
        quote.priced.backtest.trend.p_value,
        quote.priced.simulation.probability_of_payout,
        quote.priced.premium.rate_on_line,
        quote.priced.premium.risk_load,
        quote.priced.premium.expense_load,
    }
    unit_codes = {"unit.mm", "unit.days", "unit.mm_per_decade", "unit.days_per_decade"}
    stored = literal | window | rates | unit_codes

    reachable = walk(build_content(quote))

    codes = [item.code for item in reachable if isinstance(item, Coded)]
    assert codes
    for code in codes:  # every text is a code both catalogues know
        assert code in en.CATALOGUE, code
        assert code in pt_br.CATALOGUE, code
    strings = [item for item in reachable if isinstance(item, str)]
    assert set(strings) <= stored  # every string is a stored value or a unit code
    assert not any("R$" in item or "%" in item for item in strings)


@pytest.mark.req("R-8-2")
def test_the_content_does_not_depend_on_the_status_the_audit_or_the_submission() -> None:
    """A stored term sheet stays valid for the life of the quote."""
    quote = rainfall_quote()
    later = quote.model_copy(update={"status": "submitted", "audit": []})

    assert build_content(later) == build_content(quote)
