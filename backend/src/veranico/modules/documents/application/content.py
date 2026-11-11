"""What a term sheet says, before any language: sections of labelled, typed figures.

`build_content` copies value objects out of the stored quote and names every text by a
catalogue code. It formats nothing, translates nothing, computes no figure and reads no clock
and no quote status, so the content of a quote never changes (SPEC 8: figures exactly as
stored). The renderer turns it into a page for one locale.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.money import Money

SYNTHETIC_SOURCE = "synthetic"
_DATA_SOURCE_CODE = "assumption.data_source"
_UNITS = {
    "rainfall_below": ("unit.mm", "unit.mm_per_decade"),
    "dry_spell_above": ("unit.days", "unit.days_per_decade"),
}
_NOT_AVAILABLE = Coded(code="value.not_available")


@dataclass(frozen=True, slots=True)
class MoneyFigure:
    money: Money


@dataclass(frozen=True, slots=True)
class PercentFigure:
    rate: str  # a `Rate`, shown as a percentage


@dataclass(frozen=True, slots=True)
class RateFigure:
    rate: str  # a `Rate`, shown as stored


@dataclass(frozen=True, slots=True)
class QuantityFigure:
    value: float
    unit: str  # catalogue code of the text that carries the unit


@dataclass(frozen=True, slots=True)
class CoordinateFigure:
    degrees: float  # a latitude or a longitude, shown with four decimal places


@dataclass(frozen=True, slots=True)
class CountFigure:
    value: int


@dataclass(frozen=True, slots=True)
class DateFigure:
    at: datetime


@dataclass(frozen=True, slots=True)
class WindowFigure:
    start: str  # MM-DD
    end: str


@dataclass(frozen=True, slots=True)
class TextFigure:
    text: str  # shown literally: an identifier or text the user supplied


@dataclass(frozen=True, slots=True)
class CodedFigure:
    coded: Coded  # translated by the catalogue


Figure = (
    MoneyFigure
    | PercentFigure
    | RateFigure
    | QuantityFigure
    | CoordinateFigure
    | CountFigure
    | DateFigure
    | WindowFigure
    | TextFigure
    | CodedFigure
)


@dataclass(frozen=True, slots=True)
class Row:
    label: Coded
    value: Figure


@dataclass(frozen=True, slots=True)
class Section:
    title: Coded
    rows: tuple[Row, ...] = ()
    paragraphs: tuple[Coded, ...] = ()


@dataclass(frozen=True, slots=True)
class TermSheetContent:
    title: Coded
    notices: tuple[Coded, ...]  # shown under the title, before any figure
    sections: tuple[Section, ...]


def _row(label: str, value: Figure) -> Row:
    return Row(label=Coded(code=f"label.{label}"), value=value)


def _section(name: str, *rows: Row, paragraphs: tuple[Coded, ...] = ()) -> Section:
    return Section(title=Coded(code=f"section.{name}"), rows=rows, paragraphs=paragraphs)


def _text_or_not_available(value: str | None) -> Figure:
    return TextFigure(value) if value else CodedFigure(_NOT_AVAILABLE)


def _is_synthetic(quote: QuoteView) -> bool:
    """The source the quote was priced on, as `pricing` recorded it in the assumptions."""
    return any(
        coded.code == _DATA_SOURCE_CODE and coded.params.get("source") == SYNTHETIC_SOURCE
        for coded in quote.priced.assumptions
    )


def build_content(quote: QuoteView) -> TermSheetContent:
    index = quote.cover.index
    backtest = quote.priced.backtest
    simulation = quote.priced.simulation
    premium = quote.priced.premium
    unit, unit_per_decade = _UNITS[index.index_type]
    max_payout_season: Figure = (
        CountFigure(backtest.max_payout_season)
        if backtest.max_payout_season is not None
        else CodedFigure(_NOT_AVAILABLE)
    )

    sections = [
        _section(
            "quote",
            _row("quote_id", TextFigure(quote.quote_id)),
            _row("created_at", DateFigure(quote.created_at)),
            _row("location", TextFigure(quote.location.label)),
            _row("latitude", CoordinateFigure(quote.location.lat)),
            _row("longitude", CoordinateFigure(quote.location.lon)),
            _row("admin_region", _text_or_not_available(quote.location.admin_region)),
            _row("dataset_id", TextFigure(quote.dataset_id)),
        ),
        _section(
            "cover",
            _row("index_type", CodedFigure(Coded(code=f"index_type.{index.index_type}"))),
            _row("window", WindowFigure(index.window.start, index.window.end)),
            _row("trigger", QuantityFigure(index.trigger, unit)),
            _row("exit", QuantityFigure(index.exit, unit)),
            _row("limit", MoneyFigure(quote.cover.limit)),
        ),
        _section(
            "premium",
            _row("premium", MoneyFigure(premium.premium)),
            _row("rate_on_line", PercentFigure(premium.rate_on_line)),
            _row("risk_load", PercentFigure(premium.risk_load)),
            _row("expense_load", PercentFigure(premium.expense_load)),
        ),
        _section(
            "backtest",
            _row("seasons_used", CountFigure(backtest.seasons_used)),
            _row("seasons_excluded", CountFigure(len(backtest.seasons_excluded))),
            _row("trigger_frequency", PercentFigure(backtest.trigger_frequency)),
            _row("burn_cost", MoneyFigure(backtest.burn_cost)),
            _row("max_payout", MoneyFigure(backtest.max_payout)),
            _row("max_payout_season", max_payout_season),
            _row("trend_slope", QuantityFigure(backtest.trend.slope_per_decade, unit_per_decade)),
            _row("trend_p_value", RateFigure(backtest.trend.p_value)),
        ),
        _section(
            "simulation",
            _row("method", CodedFigure(Coded(code=f"method.{simulation.method}"))),
            _row("n", CountFigure(simulation.n)),
            _row("seed", CountFigure(simulation.seed)),
            _row("expected_loss", MoneyFigure(simulation.expected_loss)),
            _row("std_dev", MoneyFigure(simulation.std_dev)),
            _row("probability_of_payout", PercentFigure(simulation.probability_of_payout)),
            _row("payout_1_in_10", MoneyFigure(simulation.payout_1_in_10)),
            _row("payout_1_in_100", MoneyFigure(simulation.payout_1_in_100)),
            _row("gap_to_burn_cost", MoneyFigure(simulation.gap_to_burn_cost)),
        ),
        _section("assumptions", paragraphs=tuple(quote.priced.assumptions)),
    ]
    if backtest.warnings:
        sections.append(_section("warnings", paragraphs=tuple(backtest.warnings)))
    attribution = Coded(code="attribution", params={"year": quote.created_at.astimezone(UTC).year})
    sections.append(_section("data", paragraphs=(attribution,)))
    sections.append(_section("disclaimer", paragraphs=(Coded(code="disclaimer"),)))

    notices = (Coded(code="notice.synthetic"),) if _is_synthetic(quote) else ()
    return TermSheetContent(title=Coded(code="title"), notices=notices, sections=tuple(sections))
