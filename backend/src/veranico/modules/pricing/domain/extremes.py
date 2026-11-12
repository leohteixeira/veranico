"""Worst historical seasons of an index, with empirical return periods (SPEC 9.4).

Worst first: the lowest totals for `rainfall_below`, the longest spells for
`dry_spell_above`. A tie keeps the earlier season first. The return period of rank `r`
among `n` seasons is `(n + 1) / r` years.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from veranico.modules.pricing.domain.index import IndexType


@dataclass(frozen=True, slots=True)
class ExtremeFigures:
    season: int
    index_value: float
    rank: int  # 1 is the worst
    return_period_years: float


def extreme_seasons(
    index_type: IndexType,
    seasons: Sequence[int],
    values: Sequence[float],
    top_n: int,
) -> list[ExtremeFigures]:
    """The `top_n` worst seasons, or all of them when there are fewer."""
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    if len(seasons) != len(values):
        raise ValueError("one index value per season")
    n = len(seasons)
    lowest_is_worst = index_type == "rainfall_below"
    ordered = sorted(
        zip(seasons, values, strict=True),
        key=lambda item: (item[1] if lowest_is_worst else -item[1], item[0]),
    )
    return [
        ExtremeFigures(
            season=int(season),
            index_value=float(value),
            rank=rank,
            return_period_years=(n + 1) / rank,
        )
        for rank, (season, value) in enumerate(ordered[:top_n], start=1)
    ]
