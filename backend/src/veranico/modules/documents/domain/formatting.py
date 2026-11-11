"""Locale formats of the figures of a quote, by string operations only (SPEC 5.7, 12).

Formatting for a locale is not recomputation: no function here rounds, converts through
`float` or does arithmetic on a stored value. Money is laid out from the digits of the integer
centavos, a rate from the characters of its six-place string, a physical quantity from the
shortest text that reads back as the stored number. A malformed input raises `ValueError`:
a formatter never guesses.
"""

import calendar
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from veranico.shared.kernel.ids import Locale

_SEPARATORS: dict[str, tuple[str, str]] = {  # locale: (decimal mark, thousands mark)
    "en": (".", ","),
    "pt-BR": (",", "."),
}
_DAY_MONTH: dict[str, str] = {"en": "{day} {month}", "pt-BR": "{day} de {month}"}
_DATE: dict[str, str] = {"en": "{day} {month} {year}", "pt-BR": "{day} de {month} de {year}"}
_WINDOW: dict[str, str] = {"en": "{start} to {end}", "pt-BR": "{start} a {end}"}

_RATE = re.compile(r"\A(-?)([0-9]+)\.([0-9]{6})\Z")  # the kernel's `Rate`
_PLAIN_DECIMAL = re.compile(r"\A-?[0-9]+\.[0-9]+\Z")
_MONTH_DAY = re.compile(r"\A([0-9]{2})-([0-9]{2})\Z")
_LEAP_YEAR = 2024  # `02-29` is a valid window boundary


def _separators(locale: Locale) -> tuple[str, str]:
    try:
        return _SEPARATORS[locale]
    except KeyError:
        raise ValueError(f"unsupported locale: {locale!r}") from None


def format_money(amount_cents: int, locale: Locale) -> str:
    """`123456` → `R$ 1,234.56` (`en`) or `R$ 1.234,56` (`pt-BR`); a leading minus when negative."""
    if type(amount_cents) is not int:
        raise ValueError("money is an integer number of centavos")
    decimal, thousands = _separators(locale)
    digits = str(amount_cents)
    sign = "-" if digits.startswith("-") else ""
    digits = digits.removeprefix("-").zfill(3)
    whole, centavos = digits[:-2], digits[-2:]
    groups = []
    while whole:
        groups.append(whole[-3:])
        whole = whole[:-3]
    return f"{sign}R$ {thousands.join(reversed(groups))}{decimal}{centavos}"


def _rate_parts(rate: str) -> tuple[str, str, str]:
    match = _RATE.match(rate) if isinstance(rate, str) else None
    if match is None:
        raise ValueError("a rate is a decimal string with six places")
    return match[1], match[2], match[3]


def format_percent(rate: str, locale: Locale) -> str:
    """`0.083200` → `8.3200%`: the decimal point moves two places, every stored digit stays."""
    decimal, _ = _separators(locale)
    sign, whole, fraction = _rate_parts(rate)
    moved = (whole + fraction[:2]).lstrip("0") or "0"
    return f"{sign}{moved}{decimal}{fraction[2:]}%"


def format_rate(rate: str, locale: Locale) -> str:
    """The six-place string as stored, with the locale's decimal mark (a p-value)."""
    decimal, _ = _separators(locale)
    sign, whole, fraction = _rate_parts(rate)
    return f"{sign}{whole}{decimal}{fraction}"


def format_quantity(value: float, locale: Locale) -> str:
    """Millimetres, days, a slope or a coordinate, with the digits of the stored number.

    `repr` gives the shortest decimal text that reads back as the same `float`, so nothing is
    rounded here: `142.5` → `142.5`, `7.0` → `7.0`.
    """
    if type(value) is not float:
        raise ValueError("a quantity is a float")
    text = repr(value)
    if _PLAIN_DECIMAL.match(text) is None:  # nan, inf, or an exponent
        raise ValueError("a quantity is a finite number in plain decimal notation")
    decimal, _ = _separators(locale)
    return text.replace(".", decimal)


def _month_name(month: int, months: Sequence[str]) -> str:
    if len(months) != 12:
        raise ValueError("twelve month names are needed")
    return months[month - 1]


def format_day_month(month_day: str, locale: Locale, months: Sequence[str]) -> str:
    """`11-15` (`MM-DD`) → `15 November` or `15 de novembro`."""
    _separators(locale)
    match = _MONTH_DAY.match(month_day) if isinstance(month_day, str) else None
    if match is None:
        raise ValueError("a window boundary is MM-DD")
    month, day = int(match[1]), int(match[2])
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(_LEAP_YEAR, month)[1]:
        raise ValueError("a window boundary is a day of the calendar")
    return _DAY_MONTH[locale].format(day=day, month=_month_name(month, months))


def format_window(start: str, end: str, locale: Locale, months: Sequence[str]) -> str:
    """`11-15`, `02-15` → `15 November to 15 February`; the window may cross the year end."""
    return _WINDOW[locale].format(
        start=format_day_month(start, locale, months), end=format_day_month(end, locale, months)
    )


def format_date(value: datetime, locale: Locale, months: Sequence[str]) -> str:
    """The UTC day of a timezone-aware instant: `10 November 2026`, `10 de novembro de 2026`."""
    _separators(locale)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("a date is a timezone-aware datetime")
    day = value.astimezone(UTC)
    return _DATE[locale].format(
        day=day.day, month=_month_name(day.month, months), year=f"{day.year:04d}"
    )
