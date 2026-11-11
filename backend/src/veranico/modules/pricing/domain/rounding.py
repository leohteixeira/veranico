"""Rounding at the module boundary (SPEC 5.7).

The engine works in float64. A figure leaves `pricing` through exactly one of these
functions, applied once: money as integer centavos (half to even), rates and probabilities
as strings with six decimal places, millimetres and days with one decimal place.
"""

import math

RATE_DECIMALS = 6


def to_cents(x: float) -> int:
    """Integer centavos, rounded half to even (Python's built-in `round` for a float)."""
    _require_finite(x)
    return round(x)


def to_rate(x: float) -> str:
    """Fixed-decimal string with six places; a value that rounds to zero has no minus sign."""
    _require_finite(x)
    text = f"{x:.{RATE_DECIMALS}f}"
    return text.removeprefix("-") if float(text) == 0 else text


def to_tenth(x: float) -> float:
    """A physical quantity (millimetres, days) with one decimal place; never negative zero."""
    _require_finite(x)
    return round(x, 1) + 0.0


def cents_difference(minuend_cents: int, subtrahend_cents: int) -> int:
    """Difference of two figures already rounded, so the three numbers shown reconcile."""
    return minuend_cents - subtrahend_cents


def _require_finite(x: float) -> None:
    if not math.isfinite(x):
        raise ValueError("a figure that leaves pricing must be finite")
