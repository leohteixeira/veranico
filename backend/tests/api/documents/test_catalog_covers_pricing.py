"""The catalogues of the term sheet against the codes the real `pricing` module emits.

The other tests of this module read the eight codes and their parameters from a table. Here
the real pricing module prices fixture series (one cover per index type, one series with a
significant trend, one window that leaves a season incomplete) and every `Coded` text it
returns is checked against both catalogues: known code, an entry in each, exactly the
parameters the entry's placeholders name, and a translation that is prose, not the code.

Weather comes from `FakeClimateFacade`, so no store and no emulator is needed.
"""

import logging
from dataclasses import replace
from string import Formatter

import numpy as np
import pytest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.climate.contracts import DailySeries
from veranico.modules.documents.application.i18n import en, pt_br
from veranico.modules.documents.application.i18n.translate import translate
from veranico.modules.pricing import module as pricing_module
from veranico.modules.pricing.contracts import PricedCover, SimulationOptions
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import Locale

EIGHT_CODES = {
    "warning.trend_significant",
    "warning.seasons_excluded",
    "assumption.index_type",
    "assumption.window",
    "assumption.seasons_used",
    "assumption.simulation_method",
    "assumption.loads",
    "assumption.data_source",
}
CATALOGUES: dict[Locale, dict[str, str]] = {"en": en.CATALOGUE, "pt-BR": pt_br.CATALOGUE}
OPTIONS = SimulationOptions(n=2_000, seed=7)


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name is not None}


def drying(series: DailySeries) -> DailySeries:
    """The same series with rain falling steadily to a third: a clear downward trend."""
    factor = np.linspace(1.5, 0.5, len(series.dates))
    return replace(series, precipitation_mm=series.precipitation_mm * factor)


async def priced_covers() -> list[PricedCover]:
    climate = FakeClimateFacade()
    pricing = pricing_module.build(
        pricing_module.PricingDeps(settings=settings_for_tests(), climate=climate)
    ).facade
    steady = climate.add_series(builders.daily_series(seed=11, source="era5/open-meteo"))
    trending = climate.add_series(drying(builders.daily_series(seed=12, lat=-21.55, lon=-45.43)))
    return [
        await pricing.price(steady.dataset_id, builders.cover(), OPTIONS),
        await pricing.price(
            steady.dataset_id,
            builders.cover(index_type="dry_spell_above", start="01-10", end="03-20"),
            OPTIONS,
        ),
        # The window crosses the year end, so the last season of the series is incomplete.
        await pricing.price(
            trending.dataset_id, builders.cover(start="11-15", end="02-15"), OPTIONS
        ),
    ]


def coded_texts(priced: PricedCover) -> list[Coded]:
    return [*priced.assumptions, *priced.backtest.warnings]


@pytest.mark.req("R-8-2")
async def test_every_code_of_the_real_pricing_module_has_its_text_in_both_catalogues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    covers = await priced_covers()
    seen = [coded for priced in covers for coded in coded_texts(priced)]

    # The fixture series exercise all eight codes, the two warnings included.
    assert {coded.code for coded in seen} == EIGHT_CODES
    with caplog.at_level(logging.WARNING):
        for coded in seen:
            for locale, catalogue in CATALOGUES.items():
                assert coded.code in catalogue, coded.code
                assert set(coded.params) == placeholders(catalogue[coded.code]), coded.code
                text = translate(coded, locale)
                assert text != coded.code
                assert "{" not in text
    assert caplog.records == []  # no missing code, no parameter that did not fit


@pytest.mark.req("R-8-2")
async def test_the_enumerated_values_pricing_emits_are_translated() -> None:
    """Index type, method, source and trend direction are shown as prose, not as identifiers."""
    for priced in await priced_covers():
        for coded in coded_texts(priced):
            for locale in CATALOGUES:
                text = translate(coded, locale)
                for value in coded.params.values():
                    if isinstance(value, str) and ("_" in value or "/" in value):
                        assert value not in text, (coded.code, value)
