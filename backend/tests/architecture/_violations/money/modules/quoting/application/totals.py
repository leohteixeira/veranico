"""Breaks the money rules: rounding and arithmetic on money outside `pricing`."""

import decimal
from decimal import Decimal


class Line:
    amount_cents = 0


def rounded(value: float) -> int:
    return round(value)


def as_decimal(text: str) -> Decimal:
    return Decimal(text)


def as_qualified_decimal(text: str) -> decimal.Decimal:
    return decimal.Decimal(text)


def doubled(limit_cents: int) -> int:
    return limit_cents * 2


def total(line: Line, fee: int) -> int:
    return fee + line.amount_cents


def accumulate(lines: list[Line]) -> int:
    total_cents = 0
    for line in lines:
        total_cents += line.amount_cents
    return total_cents


def negated(premium_cents: int) -> int:
    return -premium_cents


def allowed(limit_cents: int, other_cents: int) -> bool:
    return limit_cents > other_cents and limit_cents == int(limit_cents)
