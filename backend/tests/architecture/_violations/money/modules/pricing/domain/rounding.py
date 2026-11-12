"""Clean: `pricing` is where money is computed and rounded."""


def to_cents(value: float) -> int:
    return round(value * 100)


def share(limit_cents: int, fraction: float) -> int:
    return round(limit_cents * fraction)
