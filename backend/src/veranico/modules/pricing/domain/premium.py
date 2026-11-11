"""Indicative premium (SPEC 5.6).

    premium = expected_loss + risk_load * std_dev + expense_load * expected_loss
    rate_on_line = premium / limit

The loads are parameters: their values come from configuration. Money is float centavos.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PremiumFigures:
    premium: float  # centavos
    rate_on_line: float


def premium(
    expected_loss: float,
    std_dev: float,
    risk_load: float,
    expense_load: float,
    limit_cents: float,
) -> PremiumFigures:
    amount = expected_loss + risk_load * std_dev + expense_load * expected_loss
    return PremiumFigures(premium=amount, rate_on_line=amount / limit_cents)
