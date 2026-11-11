"""Runtime grounding check (SPEC 9.5, contracts section 8).

`check_grounding` is a pure function: it finds every monetary value and percentage in an
answer and looks for each one in the tool results of the conversation and in the user's own
messages. The turn loop calls it after each answer and the evaluation suite uses the same
function as its `numbers_grounded` scorer.

The rule. A figure is grounded when it equals a source value rounded to the precision the
answer wrote it with. There is no tolerance to configure and no setting.

* Figures. Money is a number with `R$` or `BRL` before it, or `BRL`, `real` or `reais` after
  it, with an optional magnitude word (`k`, `mil`, `thousand`, `mi`, `million`, `milhão`,
  `milhões`). A percentage is a number followed by `%`, `percent` or `por cento`. Nothing else
  is a figure: millimetres, days, years, counts, coordinates, identifiers and ratios such as
  "1 in 100" are ignored.
* Number parsing. When both separators appear, the last one is the decimal separator. A
  repeated separator is grouping. A single separator followed by one, two or more than three
  digits is decimal. A single separator followed by exactly three digits is ambiguous: the
  locale gives the first reading (`en`: comma groups; `pt-BR`: dot groups) and the other
  locale's reading is the second candidate. A parsed number is an integer mantissa with a
  decimal exponent; this module uses integer arithmetic only.
* Sources. In every successful tool result, money sources are the integer leaves whose key
  ends in `_cents` (so `amount_cents` too), and percentage sources are the string leaves that
  match the `Rate` pattern, read as a fraction and multiplied by 100. An error result (a
  mapping with `error_code`) is not a source. Every number the user typed is a source for both
  kinds, with its magnitude word when it has one: a user writes "limit 300k" as often as
  "R$ 300k", and the agent repeating it is not an invention.
* Match. A figure is grounded when, for some candidate reading, a source of its kind differs
  from it by at most half a unit of the last digit written, after the magnitude word is
  applied. So `R$ 12.346` matches 1 234 567 centavos and `R$ 12.400` does not. Signs are
  compared: a minus sign directly before the number or before the currency marker makes the
  figure negative, and a hyphen between two numbers ("10-20%") is a range, not a sign.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from veranico.shared.kernel.ids import Locale

FigureKind = Literal["money", "percent"]


@dataclass(frozen=True, slots=True)
class Figure:
    text: str  # as written in the answer, with its sign, marker and magnitude word
    kind: FigureKind
    grounded: bool


@dataclass(frozen=True, slots=True)
class GroundingReport:
    figures: tuple[Figure, ...]  # every figure of the answer, in order
    ungrounded: tuple[str, ...]  # texts as written, in order, without duplicates


# A value is `mantissa * 10 ** exponent`, both integers.
_Value = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Token:
    start: int
    end: int
    kind: FigureKind | None  # None: a bare number, a source only when the user typed it
    readings: tuple[_Value, ...]


_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_MINUS = "-" + chr(0x2212)  # hyphen-minus and the typographic minus sign
# Before the number: an optional sign, the currency marker, an optional sign.
_MONEY_BEFORE = re.compile(
    rf"(?:(?<![\w)%])([{_MINUS}])\s?)?(?<!\w)(?:R\$|BRL)\s?([{_MINUS}])?$", re.I
)
_SIGN_BEFORE = re.compile(rf"(?<![\w)%])[{_MINUS}]$")
_MAGNITUDE = re.compile(r"\s?(milhões|milhão|million|thousand|mil|mi|k)\b", re.I)
_MONEY_AFTER = re.compile(r"\s?(?:de\s)?(?:BRL|reais|real)\b", re.I)
_PERCENT_AFTER = re.compile(r"\s?(?:%|percent\b|por\s+cento\b)", re.I)
_RATE = re.compile(r"-?\d+\.\d{6}")

_MAGNITUDE_EXPONENT = {
    "k": 3,
    "mil": 3,
    "thousand": 3,
    "mi": 6,
    "million": 6,
    "milhão": 6,
    "milhões": 6,
}
# Longest text looked at on each side of a number: "- BRL -" before, " por cento" after.
_LOOK_BEHIND = 12
_LOOK_AHEAD = 24


def check_grounding(
    answer: str,
    tool_results: Sequence[Mapping[str, object]],
    user_texts: Sequence[str],
    locale: Locale,
) -> GroundingReport:
    money: list[_Value] = []
    percent: list[_Value] = []
    for result in tool_results:
        if "error_code" not in result:
            _collect(result, money, percent)
    for text in user_texts:
        for token in _scan(text, locale):
            money.extend(token.readings)
            percent.extend(token.readings)

    figures: list[Figure] = []
    ungrounded: list[str] = []
    for token in _scan(answer, locale):
        if token.kind is None:
            continue
        sources = money if token.kind == "money" else percent
        grounded = any(
            _within_half_unit(reading, source) for reading in token.readings for source in sources
        )
        text = answer[token.start : token.end]
        figures.append(Figure(text=text, kind=token.kind, grounded=grounded))
        if not grounded and text not in ungrounded:
            ungrounded.append(text)
    return GroundingReport(figures=tuple(figures), ungrounded=tuple(ungrounded))


def _scan(text: str, locale: Locale) -> Iterator[_Token]:
    """Every number of `text` with its kind, span and candidate values."""
    for match in _NUMBER.finditer(text):
        start, end = match.span()
        before = text[max(0, start - _LOOK_BEHIND) : start]
        negative = False
        kind: FigureKind | None = None

        prefix = _MONEY_BEFORE.search(before)
        if prefix is not None:
            kind = "money"
            negative = prefix.group(1) is not None or prefix.group(2) is not None
            start -= len(prefix.group(0))
        elif _SIGN_BEFORE.search(before) is not None:
            negative = True
            start -= 1

        exponent_shift = 0
        magnitude = _MAGNITUDE.match(text, end, end + _LOOK_AHEAD)
        after_magnitude = end if magnitude is None else magnitude.end()
        suffix = _MONEY_AFTER.match(text, after_magnitude, after_magnitude + _LOOK_AHEAD)
        if suffix is not None:
            kind = "money"
            end = suffix.end()
        elif kind is None:
            percent = _PERCENT_AFTER.match(text, end, end + _LOOK_AHEAD)
            if percent is not None:
                kind = "percent"
                magnitude = None
                end = percent.end()
        if magnitude is not None:
            exponent_shift = _MAGNITUDE_EXPONENT[magnitude.group(1).lower()]
            end = max(end, magnitude.end())

        sign = -1 if negative else 1
        readings = tuple(
            (sign * mantissa, exponent + exponent_shift)
            for mantissa, exponent in _readings(match.group(0), locale)
        )
        yield _Token(start=start, end=end, kind=kind, readings=readings)


def _readings(number: str, locale: Locale) -> tuple[_Value, ...]:
    """Candidate values of a written number, the locale's reading first."""
    separators = [char for char in number if char in ".,"]
    if not separators:
        return ((int(number), 0),)
    if len(set(separators)) == 2:
        return (_decimal(number),)
    if len(separators) > 1:
        return (_grouped(number),)
    fraction = number.rpartition(separators[0])[2]
    if len(fraction) != 3:
        return (_decimal(number),)
    groups_first = separators[0] == ("," if locale == "en" else ".")
    if groups_first:
        return (_grouped(number), _decimal(number))
    return (_decimal(number), _grouped(number))


def _grouped(number: str) -> _Value:
    return (int(number.replace(".", "").replace(",", "")), 0)


def _decimal(number: str) -> _Value:
    """The last separator is the decimal one; every earlier separator groups."""
    cut = max(number.rfind("."), number.rfind(","))
    whole = number[:cut].replace(".", "").replace(",", "")
    fraction = number[cut + 1 :]
    return (int(whole + fraction), -len(fraction))


def _collect(node: object, money: list[_Value], percent: list[_Value]) -> None:
    """Walk one tool result and add its money and percentage sources."""
    if isinstance(node, str):
        if _RATE.fullmatch(node) is not None:
            percent.append(_rate_as_percent(node))
    elif isinstance(node, Mapping):
        for key, value in node.items():
            is_integer = isinstance(value, int) and not isinstance(value, bool)
            if is_integer and isinstance(key, str) and key.endswith("_cents"):
                money.append((value, -2))
            else:
                _collect(value, money, percent)
    elif isinstance(node, list | tuple):
        for item in node:
            _collect(item, money, percent)


def _rate_as_percent(rate: str) -> _Value:
    """`"-0.123456"` is the fraction -0.123456, so -12.3456 percent: (-123456, -4)."""
    digits = rate.lstrip("-").replace(".", "")
    sign = -1 if rate.startswith("-") else 1
    return (sign * int(digits), -4)


def _within_half_unit(figure: _Value, source: _Value) -> bool:
    """True when `source`, rounded to the last digit `figure` was written with, equals it."""
    mantissa, exponent = figure
    source_mantissa, source_exponent = source
    base = min(exponent, source_exponent)
    # Both exponents are at or above `base`, so the powers are integers (mypy types `**` as Any).
    unit: int = 10 ** (exponent - base)
    written = mantissa * unit
    actual: int = source_mantissa * 10 ** (source_exponent - base)
    return 2 * abs(actual - written) <= unit
