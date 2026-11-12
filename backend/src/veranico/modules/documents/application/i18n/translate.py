"""Lookup in the catalogues: fixed texts, month names and coded texts with parameters.

A parameter fills its placeholder already formatted for the locale (contracts conventions):
a name ending in `_cents` is money, one ending in `_rate` is a percentage, a `float` is a
physical quantity, an `int` is a plain count, `start` and `end` are window boundaries, and a
string with a `<parameter>.<value>` entry in the catalogue is an enumerated value.
"""

import logging
from collections.abc import Mapping

from veranico.modules.documents.application.i18n import en, pt_br
from veranico.modules.documents.domain.formatting import (
    format_day_month,
    format_money,
    format_percent,
    format_quantity,
)
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale

logger = logging.getLogger(__name__)

CATALOGUES: Mapping[Locale, Mapping[str, str]] = {"en": en.CATALOGUE, "pt-BR": pt_br.CATALOGUE}
_WINDOW_BOUNDARIES = frozenset({"start", "end"})  # parameters of `assumption.window`


def text(key: str, locale: Locale) -> str:
    """A fixed text of the term sheet. A missing key is a programming error (`KeyError`)."""
    return CATALOGUES[locale][key]


def months(locale: Locale) -> tuple[str, ...]:
    """The twelve month names, January first."""
    return tuple(text(f"month.{month:02d}", locale) for month in range(1, 13))


def translate(coded: Coded, locale: Locale) -> str:
    """The text of a code with its parameters formatted for the locale.

    A code the catalogue does not know, or parameters that do not fit its text, give the code
    itself and a logged warning, so a download never fails on a text.
    """
    template = CATALOGUES[locale].get(coded.code)
    if template is None:
        logger.warning("no catalogue entry for code %s (%s)", coded.code, locale)
        return coded.code
    try:
        formatted = {
            name: _format_parameter(name, value, locale) for name, value in coded.params.items()
        }
        return template.format_map(formatted)
    except (KeyError, ValueError):
        logger.warning("parameters of code %s do not fit its text (%s)", coded.code, locale)
        return coded.code


def _format_parameter(name: str, value: str | int | float, locale: Locale) -> str:
    if name.endswith("_cents"):
        if not isinstance(value, int):
            raise ValueError("a money parameter is an integer number of centavos")
        return format_money(value, locale)
    if name.endswith("_rate"):
        if not isinstance(value, str):
            raise ValueError("a rate parameter is a six-place decimal string")
        return format_percent(value, locale)
    if isinstance(value, bool):
        raise ValueError("a parameter is text or a number")
    if isinstance(value, float):
        return format_quantity(value, locale)
    if isinstance(value, int):
        return str(value)
    if name in _WINDOW_BOUNDARIES:
        return format_day_month(value, locale, months(locale))
    return CATALOGUES[locale].get(f"{name}.{value}", value)
