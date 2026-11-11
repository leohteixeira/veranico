"""The two catalogues of the term sheet and `translate` (plan 05, decisions 5, 9 and 12)."""

import logging
from string import Formatter
from typing import get_args

import pytest

from veranico.modules.climate.contracts import DatasetRef
from veranico.modules.documents.application.i18n import en, pt_br
from veranico.modules.documents.application.i18n.translate import months, text, translate
from veranico.modules.pricing.contracts import IndexType, SimulationResult
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale

LOCALES: tuple[Locale, ...] = ("en", "pt-BR")
CATALOGUES = {"en": en.CATALOGUE, "pt-BR": pt_br.CATALOGUE}
NO_BREAK_SPACE = chr(0xA0)

# The codes `pricing` emits and the parameters each carries (contracts section 4; the names
# are listed in `pricing/application/mapping.py`).
PRICING_CODES = {
    "warning.trend_significant": {"slope_per_decade", "direction"},
    "warning.seasons_excluded": {"count", "seasons"},
    "assumption.index_type": {"index_type"},
    "assumption.window": {"start", "end"},
    "assumption.seasons_used": {"seasons_used", "first_season", "last_season"},
    "assumption.simulation_method": {"method", "n", "seed"},
    "assumption.loads": {"risk_load_rate", "expense_load_rate"},
    "assumption.data_source": {"source"},
}


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name is not None}


@pytest.mark.req("R-13-3")
def test_both_catalogues_have_the_same_keys() -> None:
    assert set(en.CATALOGUE) == set(pt_br.CATALOGUE)


@pytest.mark.req("R-13-3")
def test_every_entry_has_the_same_placeholders_in_both_languages() -> None:
    different = {
        key
        for key in en.CATALOGUE
        if placeholders(en.CATALOGUE[key]) != placeholders(pt_br.CATALOGUE[key])
    }

    assert different == set()


@pytest.mark.parametrize("locale", LOCALES)
def test_every_string_is_encodable_in_the_encoding_of_the_standard_fonts(locale: Locale) -> None:
    """WinAnsiEncoding is Windows code page 1252; no string is empty or padded either."""
    for key, value in CATALOGUES[locale].items():
        value.encode("cp1252")
        assert value == value.strip(), key
        assert value, key
        assert NO_BREAK_SPACE not in value, key  # it would break the text assertions


@pytest.mark.req("R-8-2")
@pytest.mark.parametrize("locale", LOCALES)
def test_the_assumption_and_warning_entries_are_exactly_the_eight_pricing_codes(
    locale: Locale,
) -> None:
    catalogue = CATALOGUES[locale]
    coded = {key for key in catalogue if key.startswith(("assumption.", "warning."))}

    assert coded == set(PRICING_CODES)
    for code, parameters in PRICING_CODES.items():
        assert placeholders(catalogue[code]) == parameters, code


@pytest.mark.parametrize("locale", LOCALES)
def test_every_enumerated_parameter_value_has_a_text(locale: Locale) -> None:
    catalogue = CATALOGUES[locale]
    sources = get_args(DatasetRef.model_fields["source"].annotation)
    methods = get_args(SimulationResult.model_fields["method"].annotation)

    assert set(sources) == {"era5-land/cds", "era5/open-meteo", "synthetic"}
    for source in sources:
        assert f"source.{source}" in catalogue
    for index_type in get_args(IndexType):
        assert f"index_type.{index_type}" in catalogue
    for method in methods:
        assert f"method.{method}" in catalogue
    for direction in ("increasing", "decreasing"):
        assert f"direction.{direction}" in catalogue


@pytest.mark.req("R-1-1", "R-4.4-6")
@pytest.mark.parametrize("locale", LOCALES)
def test_the_disclaimer_the_attribution_and_the_synthetic_notice_exist(locale: Locale) -> None:
    catalogue = CATALOGUES[locale]

    assert placeholders(catalogue["disclaimer"]) == set()
    assert placeholders(catalogue["notice.synthetic"]) == set()
    assert placeholders(catalogue["attribution"]) == {"year"}
    # SPEC 4.4 and ADR 0017: both providers, both products and the licence are named.
    for name in ("Copernicus Climate Change Service", "ERA5-Land", "ERA5,", "Open-Meteo", "CC BY"):
        assert name in catalogue["attribution"], name


@pytest.mark.req("R-1-1")
def test_the_disclaimer_says_what_the_specification_says() -> None:
    assert text("disclaimer", "en") == (
        "Pricing is illustrative and is not actuarial or insurance advice. Veranico is a"
        " non-commercial demonstration."
    )
    assert "não constitui aconselhamento atuarial nem de seguros" in text("disclaimer", "pt-BR")
    assert "sem fins comerciais" in text("disclaimer", "pt-BR")


def test_a_synthetic_source_is_never_worded_as_real_weather_history() -> None:
    """ADR 0017: the point source is ERA5 through Open-Meteo, the cubes are ERA5-Land."""
    assert "not real weather history" in text("source.synthetic", "en")
    assert "não é histórico real" in text("source.synthetic", "pt-BR")
    for locale in LOCALES:
        assert "ERA5-Land" not in text("source.era5/open-meteo", locale)
        assert "Open-Meteo" in text("source.era5/open-meteo", locale)
        assert "ERA5-Land" in text("source.era5-land/cds", locale)
        assert "ERA5" not in text("source.synthetic", locale)


def test_months_are_twelve_names_january_first() -> None:
    assert months("en")[0] == "January"
    assert months("en")[11] == "December"
    assert months("pt-BR")[2] == "março"
    assert len(months("en")) == len(months("pt-BR")) == 12


def test_a_missing_fixed_text_is_an_error() -> None:
    with pytest.raises(KeyError):
        text("label.unknown", "en")


@pytest.mark.req("R-8-2")
def test_translate_formats_money_and_rate_parameters_for_the_locale() -> None:
    loads = Coded(
        code="assumption.loads",
        params={"risk_load_rate": "0.300000", "expense_load_rate": "0.150000"},
    )

    assert translate(loads, "en") == (
        "Premium = expected loss + 30.0000% of the standard deviation + 15.0000% of the"
        " expected loss."
    )
    assert translate(loads, "pt-BR") == (
        "Prêmio = perda esperada + 30,0000% do desvio padrão + 15,0000% da perda esperada."
    )


def test_translate_formats_a_cents_parameter_as_money(monkeypatch: pytest.MonkeyPatch) -> None:
    """No pricing code carries money today; the suffix rule of the contracts is still kept."""
    monkeypatch.setitem(en.CATALOGUE, "test.money", "Limit of {limit_cents}.")
    monkeypatch.setitem(pt_br.CATALOGUE, "test.money", "Limite de {limit_cents}.")
    coded = Coded(code="test.money", params={"limit_cents": 30000000})

    assert translate(coded, "en") == "Limit of R$ 300,000.00."
    assert translate(coded, "pt-BR") == "Limite de R$ 300.000,00."


@pytest.mark.req("R-8-2")
def test_translate_fills_counts_quantities_window_boundaries_and_enumerated_values() -> None:
    trend = Coded(
        code="warning.trend_significant",
        params={"slope_per_decade": -12.5, "direction": "decreasing"},
    )
    window = Coded(code="assumption.window", params={"start": "11-15", "end": "02-15"})
    method = Coded(
        code="assumption.simulation_method",
        params={"method": "gamma_mle", "n": 100000, "seed": 42},
    )
    source = Coded(code="assumption.data_source", params={"source": "era5/open-meteo"})
    excluded = Coded(code="warning.seasons_excluded", params={"count": 2, "seasons": "1951, 1962"})

    assert translate(trend, "en") == (
        "The index has a statistically significant downward trend (-12.5 per decade, 5% level):"
        " history may understate or overstate the current risk."
    )
    assert translate(trend, "pt-BR") == (
        "O índice tem uma tendência de queda estatisticamente significativa (-12,5 por década,"
        " nível de 5%): o histórico pode subestimar ou superestimar o risco atual."
    )
    assert translate(window, "en") == (
        "The index is measured from 15 November to 15 February; a season is named after the"
        " year it starts in."
    )
    assert translate(window, "pt-BR") == (
        "O índice é medido de 15 de novembro a 15 de fevereiro; a safra leva o nome do ano em"
        " que começa."
    )
    assert translate(method, "en") == (
        "Simulation: gamma distribution fitted by maximum likelihood; 100000 simulated seasons;"
        " seed 42."
    )
    assert translate(source, "pt-BR") == (
        "Dados meteorológicos: precipitação diária do ERA5 (Copernicus Climate Change Service,"
        " por meio do Open-Meteo)."
    )
    assert translate(excluded, "en") == (
        "Seasons with incomplete data were excluded from the backtest (2): 1951, 1962."
    )


def test_an_enumerated_value_without_a_text_is_shown_as_it_is() -> None:
    source = Coded(code="assumption.data_source", params={"source": "another-source"})

    assert translate(source, "en") == "Weather data: another-source."


@pytest.mark.parametrize("locale", LOCALES)
def test_an_unknown_code_is_returned_as_the_code_with_a_warning(
    locale: Locale, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = translate(Coded(code="assumption.unknown", params={"x": 1}), locale)

    assert result == "assumption.unknown"
    assert [record.levelname for record in caplog.records] == ["WARNING"]
    assert "assumption.unknown" in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "params",
    [
        {},  # a placeholder without its parameter
        {"risk_load_rate": "0.3", "expense_load_rate": "0.150000"},  # not a six-place rate
        {"risk_load_rate": 0.3, "expense_load_rate": "0.150000"},  # a rate that is not a string
    ],
)
def test_parameters_that_do_not_fit_give_the_code_and_a_warning(
    params: dict[str, str | int | float], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        result = translate(Coded(code="assumption.loads", params=params), "en")

    assert result == "assumption.loads"
    assert len(caplog.records) == 1
