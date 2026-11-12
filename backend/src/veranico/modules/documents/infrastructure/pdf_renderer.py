"""The term sheet as a PDF, laid out with reportlab's platypus.

* Reproducible: the document is built with `invariant=1`, which fixes the creation and
  modification dates and derives the document id from the content. No clock is read, so equal
  content and locale give equal bytes. (reportlab also honours `SOURCE_DATE_EPOCH`; it is a
  constant of the environment, not of the call.)
* Each figure is formatted once by the domain formatters and drawn as one plain string in one
  table cell, so it is never wrapped or split and text extraction returns it whole.
* Only the standard PDF fonts are used (WinAnsiEncoding); no font file is embedded. A character
  outside that encoding, possible only in text the user supplied, is drawn as a box.
* Text that goes through reportlab's paragraph markup is escaped first.
"""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from veranico.modules.documents.application.content import (
    CodedFigure,
    CoordinateFigure,
    CountFigure,
    DateFigure,
    Figure,
    MoneyFigure,
    PercentFigure,
    QuantityFigure,
    RateFigure,
    Section,
    TermSheetContent,
    TextFigure,
    WindowFigure,
)
from veranico.modules.documents.application.i18n.translate import months, translate
from veranico.modules.documents.domain.formatting import (
    format_coordinate,
    format_date,
    format_money,
    format_percent,
    format_rate,
    format_window,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_INK = colors.HexColor("#1b1f23")
_MUTED = colors.HexColor("#57606a")
_RULE = colors.HexColor("#d0d7de")
_MARGIN = 18 * mm
_LABEL_WIDTH = 78 * mm
_VALUE_WIDTH = A4[0] - 2 * _MARGIN - _LABEL_WIDTH

_TITLE = ParagraphStyle(
    "title", fontName=_FONT_BOLD, fontSize=15, leading=19, textColor=_INK, alignment=TA_LEFT
)
_NOTICE = ParagraphStyle(
    "notice", fontName=_FONT_BOLD, fontSize=9.5, leading=13, textColor=_INK, spaceBefore=6
)
_HEADING = ParagraphStyle(
    "heading", fontName=_FONT_BOLD, fontSize=10.5, leading=14, textColor=_INK, spaceBefore=10
)
_BODY = ParagraphStyle(
    "body", fontName=_FONT, fontSize=9, leading=12.5, textColor=_INK, spaceBefore=2
)
_CELL = ParagraphStyle("cell", fontName=_FONT, fontSize=9, leading=11.5, textColor=_INK)
_TABLE = TableStyle(
    [
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), _INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RULE),
    ]
)


class ReportlabTermSheetRenderer:
    """Implements the `TermSheetRenderer` port."""

    def render(self, content: TermSheetContent, locale: Locale) -> bytes:
        buffer = io.BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=_MARGIN,
            rightMargin=_MARGIN,
            topMargin=_MARGIN,
            bottomMargin=_MARGIN,
            title=translate(content.title, locale),
            author="Veranico",
            invariant=1,
            pageCompression=1,
        )
        story: list[Flowable] = [_paragraph(content.title, locale, _TITLE)]
        story += [_paragraph(notice, locale, _NOTICE) for notice in content.notices]
        for section in content.sections:
            story += _section(section, locale)
        document.build(story)
        return buffer.getvalue()


def _paragraph(coded: Coded, locale: Locale, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(translate(coded, locale)), style)


def _section(section: Section, locale: Locale) -> list[Flowable]:
    flowables: list[Flowable] = [_paragraph(section.title, locale, _HEADING)]
    if section.rows:
        flowables.append(Spacer(1, 2))
        cells = [[translate(row.label, locale), _cell(row.value, locale)] for row in section.rows]
        flowables.append(
            Table(cells, colWidths=[_LABEL_WIDTH, _VALUE_WIDTH], style=_TABLE, hAlign="LEFT")
        )
    flowables += [_paragraph(coded, locale, _BODY) for coded in section.paragraphs]
    return flowables


def _cell(figure: Figure, locale: Locale) -> str | Paragraph:
    """One plain string per figure; only literal text, which may be long, is a paragraph."""
    match figure:
        case MoneyFigure(money=money):
            return format_money(money.amount_cents, locale)
        case PercentFigure(rate=rate):
            return format_percent(rate, locale)
        case RateFigure(rate=rate):
            return format_rate(rate, locale)
        case QuantityFigure(value=value, unit=unit):
            return translate(Coded(code=unit, params={"value": value}), locale)
        case CoordinateFigure(degrees=degrees):
            return format_coordinate(degrees, locale)
        case CountFigure(value=count):
            return str(count)
        case DateFigure(at=at):
            return format_date(at, locale, months(locale))
        case WindowFigure(start=start, end=end):
            return format_window(start, end, locale, months(locale))
        case CodedFigure(coded=coded):
            return translate(coded, locale)
        case TextFigure(text=text):
            return Paragraph(escape(text), _CELL)
