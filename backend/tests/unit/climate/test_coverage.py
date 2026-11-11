"""The wanted range of years and what a store still lacks."""

from datetime import date

import pytest

from veranico.modules.climate.domain.coverage import last_complete_year, missing_years

pytestmark = pytest.mark.req("R-4-2")


def test_last_complete_year_on_the_first_of_january() -> None:
    assert last_complete_year(date(2026, 1, 1)) == 2025


def test_last_complete_year_on_the_last_of_december() -> None:
    # 31 December is not over yet, so its year is not complete.
    assert last_complete_year(date(2026, 12, 31)) == 2025


def test_an_empty_store_misses_every_wanted_year() -> None:
    assert missing_years(None, None, 2020, 2023) == [2020, 2021, 2022, 2023]


def test_a_store_ending_one_year_short_misses_that_year() -> None:
    assert missing_years(1950, 2024, 1950, 2025) == [2025]


def test_a_complete_store_misses_nothing() -> None:
    assert missing_years(1950, 2025, 1950, 2025) == []
    assert missing_years(1940, 2030, 1950, 2025) == []


def test_a_store_starting_late_misses_the_early_years() -> None:
    assert missing_years(1952, 2025, 1950, 2025) == [1950, 1951]


def test_a_store_short_on_both_sides() -> None:
    assert missing_years(1951, 2024, 1950, 2025) == [1950, 2025]
