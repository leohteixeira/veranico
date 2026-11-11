"""Breaks the boundary: `alpha` reaches into the internals of `beta`."""

from shop.modules.beta.domain.stock import LEVEL


def available() -> int:
    return LEVEL
