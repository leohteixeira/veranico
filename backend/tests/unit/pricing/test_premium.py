"""Indicative premium (SPEC 5.6): hand-computed amounts in centavos."""

import pytest

from veranico.modules.pricing.domain.premium import premium
from veranico.modules.pricing.domain.rounding import to_rate

EXPECTED_LOSS = 1_000_000.0
STD_DEV = 2_000_000.0
LIMIT_CENTS = 30_000_000.0


@pytest.mark.req("R-5.6-1")
def test_premium_is_expected_loss_plus_risk_load_plus_expense_load() -> None:
    # 1,000,000 + 0.3 x 2,000,000 + 0.15 x 1,000,000
    figures = premium(EXPECTED_LOSS, STD_DEV, 0.3, 0.15, LIMIT_CENTS)

    assert figures.premium == pytest.approx(1_750_000, abs=1e-6)


@pytest.mark.req("R-5.6-2")
def test_rate_on_line_is_the_premium_over_the_limit() -> None:
    figures = premium(EXPECTED_LOSS, STD_DEV, 0.3, 0.15, LIMIT_CENTS)

    assert figures.rate_on_line == pytest.approx(1_750_000 / 30_000_000)
    assert to_rate(figures.rate_on_line) == "0.058333"


@pytest.mark.req("R-5.6-1")
def test_zero_loads_return_the_expected_loss() -> None:
    figures = premium(EXPECTED_LOSS, STD_DEV, 0.0, 0.0, LIMIT_CENTS)

    assert figures.premium == EXPECTED_LOSS
    assert to_rate(figures.rate_on_line) == "0.033333"


@pytest.mark.req("R-5.6-1")
@pytest.mark.req("R-5.6-3")
def test_risk_load_alone_adds_its_share_of_the_standard_deviation() -> None:
    # 0.4 instead of 0.3: 0.1 x 2,000,000 more
    figures = premium(EXPECTED_LOSS, STD_DEV, 0.4, 0.15, LIMIT_CENTS)

    assert figures.premium == pytest.approx(1_950_000, abs=1e-6)
    # only the risk load: 1,000,000 + 0.3 x 2,000,000
    assert premium(EXPECTED_LOSS, STD_DEV, 0.3, 0.0, LIMIT_CENTS).premium == pytest.approx(
        1_600_000, abs=1e-6
    )


@pytest.mark.req("R-5.6-1")
@pytest.mark.req("R-5.6-3")
def test_expense_load_alone_adds_its_share_of_the_expected_loss() -> None:
    # 0.25 instead of 0.15: 0.1 x 1,000,000 more
    figures = premium(EXPECTED_LOSS, STD_DEV, 0.3, 0.25, LIMIT_CENTS)

    assert figures.premium == pytest.approx(1_850_000, abs=1e-6)
    # only the expense load: 1,000,000 + 0.15 x 1,000,000
    assert premium(EXPECTED_LOSS, STD_DEV, 0.0, 0.15, LIMIT_CENTS).premium == pytest.approx(
        1_150_000, abs=1e-6
    )


@pytest.mark.req("R-5.6-1")
def test_no_expected_loss_and_no_deviation_gives_a_zero_premium() -> None:
    figures = premium(0.0, 0.0, 0.3, 0.15, LIMIT_CENTS)

    assert figures.premium == 0.0
    assert figures.rate_on_line == 0.0
