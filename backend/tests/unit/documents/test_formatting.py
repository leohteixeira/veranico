"""Locale formats of stored figures (plan 05, decision 1): string operations, no recomputation.

Every expected string is a literal written by hand.
"""

import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from veranico.modules.documents.domain.formatting import (
    format_date,
    format_day_month,
    format_money,
    format_percent,
    format_quantity,
    format_rate,
    format_window,
)

EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
PT_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize(
    ("amount_cents", "english", "portuguese"),
    [
        (0, "R$ 0.00", "R$ 0,00"),
        (5, "R$ 0.05", "R$ 0,05"),
        (99, "R$ 0.99", "R$ 0,99"),
        (100, "R$ 1.00", "R$ 1,00"),
        (123456, "R$ 1,234.56", "R$ 1.234,56"),
        (30000000, "R$ 300,000.00", "R$ 300.000,00"),
        (100000000000, "R$ 1,000,000,000.00", "R$ 1.000.000.000,00"),
        (-5, "-R$ 0.05", "-R$ 0,05"),
        (-123456, "-R$ 1,234.56", "-R$ 1.234,56"),
        (-100000, "-R$ 1,000.00", "-R$ 1.000,00"),
    ],
)
def test_money_is_laid_out_from_the_digits_of_the_centavos(
    amount_cents: int, english: str, portuguese: str
) -> None:
    assert format_money(amount_cents, "en") == english
    assert format_money(amount_cents, "pt-BR") == portuguese


@pytest.mark.parametrize("malformed", [12.5, 1234.0, "100", None, True])
def test_money_that_is_not_an_integer_is_rejected(malformed: Any) -> None:
    with pytest.raises(ValueError, match="centavos"):
        format_money(malformed, "en")


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize(
    ("rate", "english", "portuguese"),
    [
        ("0.083200", "8.3200%", "8,3200%"),
        ("0.000001", "0.0001%", "0,0001%"),
        ("1.000000", "100.0000%", "100,0000%"),
        ("0.500000", "50.0000%", "50,0000%"),
        ("0.000000", "0.0000%", "0,0000%"),
        ("12.345678", "1234.5678%", "1234,5678%"),
        ("-0.012500", "-1.2500%", "-1,2500%"),
    ],
)
def test_a_percentage_moves_the_decimal_point_and_keeps_every_stored_digit(
    rate: str, english: str, portuguese: str
) -> None:
    assert format_percent(rate, "en") == english
    assert format_percent(rate, "pt-BR") == portuguese


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize(
    ("rate", "english", "portuguese"),
    [
        ("0.031200", "0.031200", "0,031200"),
        ("1.000000", "1.000000", "1,000000"),
        ("-0.500000", "-0.500000", "-0,500000"),
    ],
)
def test_a_rate_shown_as_stored_only_swaps_the_decimal_mark(
    rate: str, english: str, portuguese: str
) -> None:
    assert format_rate(rate, "en") == english
    assert format_rate(rate, "pt-BR") == portuguese


@pytest.mark.parametrize(
    "malformed", ["0.0832", "0.0832000", "8.32%", ".083200", "abc", "0,083200", "0.083200\n", 0.5]
)
def test_a_malformed_rate_is_rejected(malformed: Any) -> None:
    with pytest.raises(ValueError, match="six places"):
        format_percent(malformed, "en")
    with pytest.raises(ValueError, match="six places"):
        format_rate(malformed, "pt-BR")


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize(
    ("value", "english", "portuguese"),
    [
        (142.5, "142.5", "142,5"),
        (7.0, "7.0", "7,0"),
        (0.0, "0.0", "0,0"),
        (-12.5, "-12.5", "-12,5"),
        (-21.2456, "-21.2456", "-21,2456"),  # a coordinate keeps the digits it was stored with
    ],
)
def test_a_quantity_keeps_the_digits_of_the_stored_number(
    value: float, english: str, portuguese: str
) -> None:
    assert format_quantity(value, "en") == english
    assert format_quantity(value, "pt-BR") == portuguese


@pytest.mark.parametrize("malformed", [math.nan, math.inf, -math.inf, 1e22, 7, "7.0", True, None])
def test_a_quantity_that_is_not_a_plain_finite_float_is_rejected(malformed: Any) -> None:
    with pytest.raises(ValueError, match="quantity"):
        format_quantity(malformed, "en")


@pytest.mark.req("R-8-2")
def test_a_window_names_day_and_month_and_may_cross_the_year_end() -> None:
    assert format_window("11-15", "02-15", "en", EN_MONTHS) == "15 November to 15 February"
    assert format_window("11-15", "02-15", "pt-BR", PT_MONTHS) == "15 de novembro a 15 de fevereiro"
    assert format_window("09-01", "10-31", "en", EN_MONTHS) == "1 September to 31 October"
    assert format_day_month("02-29", "en", EN_MONTHS) == "29 February"
    assert format_day_month("03-01", "pt-BR", PT_MONTHS) == "1 de março"


@pytest.mark.parametrize(
    "malformed", ["13-01", "00-10", "02-30", "04-31", "11-00", "1-5", "11/15", "1115", "", None]
)
def test_a_malformed_window_boundary_is_rejected(malformed: Any) -> None:
    with pytest.raises(ValueError, match="window boundary"):
        format_day_month(malformed, "en", EN_MONTHS)
    with pytest.raises(ValueError, match="window boundary"):
        format_window("11-15", malformed, "en", EN_MONTHS)


@pytest.mark.req("R-8-2")
def test_a_date_is_the_utc_day_of_the_instant() -> None:
    created = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    late_in_sao_paulo = datetime(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-3)))

    assert format_date(created, "en", EN_MONTHS) == "10 November 2026"
    assert format_date(created, "pt-BR", PT_MONTHS) == "10 de novembro de 2026"
    assert format_date(late_in_sao_paulo, "en", EN_MONTHS) == "1 January 2027"


def test_a_date_without_a_timezone_is_rejected() -> None:
    naive = datetime(2026, 11, 10, 12, 0)  # noqa: DTZ001 - the naive value is the case under test

    with pytest.raises(ValueError, match="timezone-aware"):
        format_date(naive, "en", EN_MONTHS)
    with pytest.raises(ValueError, match="timezone-aware"):
        format_date("2026-11-10", "en", EN_MONTHS)  # type: ignore[arg-type]  # wrong on purpose


def test_month_names_must_be_twelve() -> None:
    with pytest.raises(ValueError, match="twelve"):
        format_day_month("11-15", "en", EN_MONTHS[:11])
    with pytest.raises(ValueError, match="twelve"):
        format_date(datetime(2026, 11, 10, tzinfo=UTC), "en", ())


def test_an_unsupported_locale_is_rejected() -> None:
    locale: Any = "es"

    for call in (
        lambda: format_money(100, locale),
        lambda: format_percent("0.500000", locale),
        lambda: format_rate("0.500000", locale),
        lambda: format_quantity(1.5, locale),
        lambda: format_day_month("11-15", locale, EN_MONTHS),
        lambda: format_date(datetime(2026, 11, 10, tzinfo=UTC), locale, EN_MONTHS),
    ):
        with pytest.raises(ValueError, match="unsupported locale"):
            call()
