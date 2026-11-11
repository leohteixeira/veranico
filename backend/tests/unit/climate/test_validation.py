"""Validation before any write: each rule fails on a three-day example."""

import numpy as np
import pytest

from veranico.modules.climate.domain.errors import WeatherDataError
from veranico.modules.climate.domain.validation import validate_daily
from veranico.shared.kernel.errors import DomainError

pytestmark = pytest.mark.req("R-4.4-1")


def days(*values: str) -> np.ndarray:
    return np.array(values, dtype="datetime64[D]")


def rain(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


def test_a_valid_series_passes_and_reports_no_missing_day() -> None:
    assert validate_daily(days("2020-01-01", "2020-01-02", "2020-01-03"), rain(0.0, 2.5, 11.0)) == 0


def test_a_series_may_cross_a_month_and_a_leap_day() -> None:
    assert validate_daily(days("2020-02-28", "2020-02-29", "2020-03-01"), rain(1.0, 0.0, 3.0)) == 0


def test_missing_values_are_allowed_and_counted() -> None:
    dates = days("2020-01-01", "2020-01-02", "2020-01-03")
    assert validate_daily(dates, rain(np.nan, 2.5, np.nan)) == 2


def test_a_duplicate_date_fails() -> None:
    with pytest.raises(WeatherDataError, match="duplicate"):
        validate_daily(days("2020-01-01", "2020-01-02", "2020-01-02"), rain(0.0, 1.0, 1.0))


def test_a_gap_fails() -> None:
    with pytest.raises(WeatherDataError, match="gap"):
        validate_daily(days("2020-01-01", "2020-01-02", "2020-01-04"), rain(0.0, 1.0, 1.0))


def test_dates_out_of_order_fail() -> None:
    with pytest.raises(WeatherDataError, match="order"):
        validate_daily(days("2020-01-02", "2020-01-01", "2020-01-03"), rain(0.0, 1.0, 1.0))


def test_a_negative_value_fails() -> None:
    with pytest.raises(WeatherDataError, match="negative"):
        validate_daily(days("2020-01-01", "2020-01-02", "2020-01-03"), rain(0.0, -0.1, 1.0))


def test_unequal_lengths_fail() -> None:
    with pytest.raises(WeatherDataError, match="length"):
        validate_daily(days("2020-01-01", "2020-01-02", "2020-01-03"), rain(0.0, 1.0))


def test_an_empty_series_fails() -> None:
    with pytest.raises(WeatherDataError, match="empty"):
        validate_daily(days(), rain())


def test_the_error_is_internal_and_not_a_domain_error() -> None:
    # It must surface as a server failure, never as a client-facing problem code.
    assert not issubclass(WeatherDataError, DomainError)
