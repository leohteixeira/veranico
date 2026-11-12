"""The grounding rule of SPEC 9.5: figures of an answer against tool results and user text."""

from collections.abc import Mapping, Sequence

import pytest

from veranico.modules.assistant.domain.grounding import GroundingReport, check_grounding
from veranico.shared.kernel.ids import Locale

pytestmark = [pytest.mark.req("R-9.5-1"), pytest.mark.req("R-9.5-4")]

# 1,234,567 centavos = R$ 12,345.67.
PREMIUM = [{"quote_id": "Q-7K3M9P", "premium": {"premium": {"amount_cents": 1_234_567}}}]
# R$ 300,000.00.
LIMIT = [{"cover": {"limit": {"amount_cents": 30_000_000}}}]
# 0.123456 as a fraction = 12.3456 %.
RATE = [{"trigger_frequency": "0.123456"}]
# What locale-aware formatters emit: a no-break space after "R$", a typographic minus sign.
NBSP = chr(0x00A0)
MINUS = chr(0x2212)


def check(
    answer: str,
    results: Sequence[Mapping[str, object]],
    locale: Locale = "en",
    user_texts: Sequence[str] = (),
) -> GroundingReport:
    return check_grounding(answer, results, user_texts, locale)


def grounded(
    answer: str,
    results: Sequence[Mapping[str, object]],
    locale: Locale = "en",
    user_texts: Sequence[str] = (),
) -> bool:
    report = check(answer, results, locale, user_texts)
    assert len(report.figures) == 1, report
    return report.figures[0].grounded


@pytest.mark.parametrize(
    ("answer", "locale"),
    [
        ("The premium is R$ 12,345.67.", "en"),
        ("The premium is R$12,345.67 for quote Q-7K3M9P.", "en"),
        ("The premium is BRL 12,345.67.", "en"),
        ("The premium is 12,345.67 BRL.", "en"),
        ("O prêmio é R$ 12.345,67.", "pt-BR"),
        (f"O prêmio é R${NBSP}12.345,67.", "pt-BR"),
        ("O prêmio é de 12.345,67 reais.", "pt-BR"),
    ],
)
def test_money_en_and_pt_br_formats(answer: str, locale: Locale) -> None:
    report = check(answer, PREMIUM, locale)

    assert [(figure.kind, figure.grounded) for figure in report.figures] == [("money", True)]
    assert report.ungrounded == ()


def test_figure_text_is_the_span_as_written() -> None:
    report = check("Premium: R$ 12,345.67. Limit: 300 mil reais.", PREMIUM + LIMIT)

    assert [figure.text for figure in report.figures] == ["R$ 12,345.67", "300 mil reais"]


def test_both_separators_resolve_by_position() -> None:
    # The last separator is the decimal one, whatever the locale hint says.
    assert grounded("R$ 12.345,67", PREMIUM, "en")
    assert grounded("R$ 12,345.67", PREMIUM, "pt-BR")
    # A repeated separator is grouping: 123,456,700 centavos = 1,234,567 reais.
    assert grounded("R$ 1.234.567", [{"limit_cents": 123_456_700}], "en")
    assert grounded("R$ 1,234,567", [{"limit_cents": 123_456_700}], "pt-BR")


def test_single_separator_with_other_than_three_digits_is_decimal() -> None:
    assert grounded("R$ 12345,67", PREMIUM, "en")
    assert grounded("R$ 12345.7", PREMIUM, "pt-BR")
    assert grounded("R$ 12345.6700", PREMIUM, "pt-BR")


def test_ambiguous_three_digit_group_tries_both_locales() -> None:
    # "12.346" is 12,346 in pt-BR and 12.346 in en. R$ 12,345.67 rounds to 12,346.
    assert grounded("R$ 12.346", PREMIUM, "pt-BR")
    assert grounded("R$ 12.346", PREMIUM, "en")  # second reading
    assert grounded("R$ 12,346", PREMIUM, "en")
    assert grounded("R$ 12,346", PREMIUM, "pt-BR")  # second reading
    # 0.123460 = 12.346 %: the decimal reading, first in en and second in pt-BR.
    exact = [{"rate_on_line": "0.123460"}]
    assert grounded("12.346%", exact, "en")
    assert grounded("12.346%", exact, "pt-BR")


@pytest.mark.parametrize(
    ("answer", "locale"),
    [
        ("R$ 300k", "en"),
        ("R$ 300K", "en"),
        ("R$ 300 thousand", "en"),
        ("R$ 0.3 million", "en"),
        ("R$ 300 mil", "pt-BR"),
        ("300 mil reais", "pt-BR"),
        ("R$ 0,3 milhão", "pt-BR"),
        ("R$ 0,3 mi", "pt-BR"),
    ],
)
def test_magnitude_words_scale_value_and_precision(answer: str, locale: Locale) -> None:
    assert grounded(answer, LIMIT, locale)


def test_magnitude_words_scale_the_written_precision_too() -> None:
    # R$ 12,345.67: "12 thousand" is written to the thousand, "12.3 thousand" to the hundred.
    assert grounded("R$ 12 thousand", PREMIUM)
    assert grounded("R$ 12.3 thousand", PREMIUM)
    assert not grounded("R$ 12.4 thousand", PREMIUM)
    assert not grounded("R$ 13 thousand", PREMIUM)
    # 200,000,000 centavos = R$ 2,000,000.
    assert grounded("2 milhões de reais", [{"limit_cents": 200_000_000}], "pt-BR")


@pytest.mark.parametrize(
    ("answer", "locale"),
    [
        ("It paid in 8.5% of seasons.", "en"),
        ("It paid in 8.5 % of seasons.", "en"),
        ("It paid in 8.5 percent of seasons.", "en"),
        ("Pagou em 8,5% das safras.", "pt-BR"),
        ("Pagou em 8,5 por cento das safras.", "pt-BR"),
    ],
)
def test_percent_matches_rate_times_hundred(answer: str, locale: Locale) -> None:
    report = check(answer, [{"backtest": {"trigger_frequency": "0.085000"}}], locale)

    assert [(figure.kind, figure.grounded) for figure in report.figures] == [("percent", True)]


# The forms prompt v5 asks for, with figures of the 2026-11-11 campaign: money with the
# separators of the answer's language, whole reais allowed, and a rounded percentage alone.
CAMPAIGN = [
    {
        "premium": {"premium": {"amount_cents": 4_063_788}},
        "cover": {"limit": {"amount_cents": 30_000_000}},
        "backtest": {"trigger_frequency": "0.144737"},
    }
]


@pytest.mark.parametrize(
    ("answer", "locale"),
    [
        ("The premium is R$ 40,637.88 for quote Q-P6PR06.", "en"),
        ("The premium is R$ 40,638.", "en"),
        ("The limit is R$ 300,000.", "en"),
        ("The limit is R$ 300,000.00.", "en"),
        ("It would have paid in 14.5% of seasons.", "en"),
        ("It would have paid in 14.47% of seasons.", "en"),
        ("It would have paid in 14% of seasons.", "en"),
        ("O prêmio da cotação Q-P6PR06 é R$ 40.637,88.", "pt-BR"),
        ("O prêmio é R$ 40.638.", "pt-BR"),
        ("O limite é R$ 300.000,00.", "pt-BR"),
        ("O limite é R$ 300.000.", "pt-BR"),
        ("Teria pago em 14,5% das safras.", "pt-BR"),
        ("Teria pago em 14,47% das safras.", "pt-BR"),
    ],
)
def test_the_forms_the_prompt_asks_for_are_grounded(answer: str, locale: Locale) -> None:
    report = check(answer, CAMPAIGN, locale)

    assert len(report.figures) == 1, report
    assert report.ungrounded == ()


def test_rates_inside_lists_are_sources() -> None:
    results = [{"seasons": [{"season": 1999, "share": "0.250000"}]}]

    assert grounded("25%", results)


@pytest.mark.parametrize("answer", ["12%", "12.3%", "12.35%", "12.346%", "12.3456%"])
def test_rounding_within_written_precision_is_grounded(answer: str) -> None:
    assert grounded(answer, RATE)


@pytest.mark.parametrize("answer", ["R$ 12,346", "R$ 12,345.7", "R$ 12,345.67", "R$ 12,345.670"])
def test_money_rounding_within_written_precision_is_grounded(answer: str) -> None:
    assert grounded(answer, PREMIUM)


def test_exactly_half_a_unit_is_grounded() -> None:
    # 12.5 written as "12" or "13": both are half a unit away, whichever way the writer rounds.
    half = [{"rate_on_line": "0.125000"}]

    assert grounded("12%", half)
    assert grounded("13%", half)


@pytest.mark.parametrize("answer", ["13%", "12.4%", "12.34%", "12.347%", "1.2%", "123%"])
def test_one_unit_beyond_precision_is_flagged(answer: str) -> None:
    assert not grounded(answer, RATE)


@pytest.mark.parametrize(
    ("answer", "locale"),
    [
        ("R$ 12,347", "en"),
        ("R$ 12,345", "en"),
        ("R$ 12,345.68", "en"),
        ("R$ 12.400", "pt-BR"),
        ("R$ 12.400", "en"),
    ],
)
def test_money_one_unit_beyond_precision_is_flagged(answer: str, locale: Locale) -> None:
    assert not grounded(answer, PREMIUM, locale)


def test_kinds_do_not_cross() -> None:
    # A rate is not a money source and centavos are not a percentage source.
    assert not grounded("R$ 12.35", RATE)
    assert not grounded("12,345.67%", PREMIUM)


@pytest.mark.parametrize("answer", ["-R$ 500", "R$ -500", f"{MINUS}R$ 500.00", "-500 reais"])
def test_negative_amount_matches_negative_source(answer: str) -> None:
    negative = [{"simulation": {"gap_to_burn_cost": {"amount_cents": -50_000}}}]

    assert grounded(answer, negative)


def test_signs_are_compared() -> None:
    negative = [{"gap_to_burn_cost": {"amount_cents": -50_000}}]
    positive = [{"gap_to_burn_cost": {"amount_cents": 50_000}}]

    assert not grounded("R$ 500", negative)
    assert not grounded("-R$ 500", positive)
    assert grounded("-0.5%", [{"p": "-0.005000"}])
    assert not grounded("0.5%", [{"p": "-0.005000"}])


def test_a_hyphen_between_two_numbers_is_a_range_not_a_sign() -> None:
    results = [{"low": "0.100000", "high": "0.200000"}]

    report = check("Between 10-20% of seasons.", results)

    assert [(figure.text, figure.grounded) for figure in report.figures] == [("20%", True)]


def test_figure_absent_from_results_is_flagged() -> None:
    report = check(
        "A rough premium would be R$ 9,999, about 3% of the limit.",
        PREMIUM + RATE,
        user_texts=["Coffee farm near Varginha, R$ 300k limit"],
    )

    assert report.ungrounded == ("R$ 9,999", "3%")
    assert [figure.grounded for figure in report.figures] == [False, False]


def test_without_any_source_every_figure_is_flagged() -> None:
    assert check("R$ 100 and 5%", []).ungrounded == ("R$ 100", "5%")


@pytest.mark.parametrize(
    ("user_text", "answer", "locale"),
    [
        ("Coffee farm, R$ 300k limit", "You asked for a limit of R$ 300,000.", "en"),
        ("limit of 300 thousand", "You asked for a limit of R$ 300,000.", "en"),
        ("limite de 300 mil", "O limite pedido é de R$ 300.000,00.", "pt-BR"),
        ("pay when rain is 30% below normal", "A trigger 30% below normal, then.", "en"),
        ("limite 250000", "Limite de R$ 250 mil.", "pt-BR"),
    ],
)
def test_figure_typed_by_the_user_is_grounded(user_text: str, answer: str, locale: Locale) -> None:
    assert grounded(answer, [], locale, [user_text])


def test_user_figure_obeys_the_same_precision_rule() -> None:
    assert not grounded("R$ 301,000", [], "en", ["R$ 300k limit"])


def test_millimetres_days_ids_and_ratios_are_ignored() -> None:
    answer = (
        "Rainfall of 123.4 mm over 45 days in 2019 at -21.55, -45.43 (cell 86a8100c7ffffff, "
        "dataset cube:sul-de-minas:7:12), quote Q-7K3M9P, window 11-15 to 02-15, a 1 in 100 "
        "season, 3 times out of 74 seasons, 100,000 simulated seasons, seed 42."
    )

    report = check(answer, PREMIUM)

    assert report.figures == ()
    assert report.ungrounded == ()


def test_error_results_are_not_sources() -> None:
    error = {
        "error_code": "invalid_cover",
        "message": "exit must be below the trigger",
        "retryable": False,
        "details": {"limit_cents": 50_000, "rate_on_line": "0.050000"},
    }

    assert check("R$ 500 at 5%", [error]).ungrounded == ("R$ 500", "5%")


def test_only_cents_keys_and_rate_strings_are_sources() -> None:
    results = [{"seasons_used": 74, "trigger": 500, "index_value": 12.5, "label": "12.50"}]

    assert check("R$ 74, R$ 500, 12.5%", results).ungrounded == ("R$ 74", "R$ 500", "12.5%")


def test_report_lists_ungrounded_as_written_without_duplicates() -> None:
    answer = "R$ 9,999 now, 77% later, R$ 12,345.67 for the quote and R$ 9,999 again."

    report = check(answer, PREMIUM)

    assert [figure.text for figure in report.figures] == [
        "R$ 9,999",
        "77%",
        "R$ 12,345.67",
        "R$ 9,999",
    ]
    assert report.ungrounded == ("R$ 9,999", "77%")


def test_same_input_gives_same_report() -> None:
    answer = "R$ 12,346 at 12.3%, not R$ 1 and not 99%."

    assert check(answer, PREMIUM + RATE) == check(answer, PREMIUM + RATE)


def test_sources_are_not_mutated() -> None:
    results = [{"premium": {"amount_cents": 1_234_567}, "seasons": [{"p": "0.100000"}]}]
    before = repr(results)

    check("R$ 12,346 and 10%", results)

    assert repr(results) == before
