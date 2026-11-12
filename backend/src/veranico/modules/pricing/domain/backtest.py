"""Backtest of a cover over the usable seasons (SPEC 5.4).

Money is float centavos here; it is rounded once, at the module boundary.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import stats

from veranico.modules.pricing.domain.errors import InsufficientHistoryError
from veranico.modules.pricing.domain.index import IndexType, SeasonIndex
from veranico.modules.pricing.domain.payout import payout_amounts, validate_cover

SIGNIFICANCE_LEVEL = 0.05
YEARS_PER_DECADE = 10.0


@dataclass(frozen=True, slots=True)
class TrendFigures:
    slope_per_decade: float  # index units per ten years
    p_value: float
    significant: bool


@dataclass(frozen=True, slots=True)
class BacktestFigures:
    seasons: tuple[int, ...]  # usable seasons, ascending
    index_values: npt.NDArray[np.float64]
    payouts: npt.NDArray[np.float64]  # centavos, one per usable season
    seasons_excluded: tuple[int, ...]
    trigger_frequency: float
    burn_cost: float  # centavos
    max_payout: float  # centavos
    max_payout_season: int | None  # the earliest on a tie; None when nothing paid
    trend: TrendFigures

    @property
    def seasons_used(self) -> int:
        return len(self.seasons)


def paying(
    index_type: IndexType, index_values: npt.ArrayLike, trigger: float
) -> npt.NDArray[np.bool_]:
    """Whether each index value lies strictly beyond the trigger, where the payout starts."""
    values = np.asarray(index_values, dtype=np.float64)
    beyond = trigger - values if index_type == "rainfall_below" else values - trigger
    return np.asarray(beyond > 0, dtype=np.bool_)


def require_history(seasons_used: int, min_seasons: int) -> None:
    if seasons_used < min_seasons:
        raise InsufficientHistoryError(
            f"{seasons_used} usable seasons, at least {min_seasons} are needed"
        )


def trend(seasons: tuple[int, ...], index_values: npt.NDArray[np.float64]) -> TrendFigures:
    """Linear regression of the index on the season year, two-sided test of a zero slope.

    A constant series, or fewer than three seasons, has no measurable trend: slope 0 and
    p-value 1 (SciPy returns NaN for the p-value in both cases).
    """
    if len(seasons) < 3 or bool(np.all(index_values == index_values[0])):
        return TrendFigures(slope_per_decade=0.0, p_value=1.0, significant=False)
    fit = stats.linregress(np.asarray(seasons, dtype=np.float64), index_values)
    p_value = float(fit.pvalue)
    return TrendFigures(
        slope_per_decade=float(fit.slope) * YEARS_PER_DECADE,
        p_value=p_value,
        significant=p_value < SIGNIFICANCE_LEVEL,
    )


def backtest(
    season_index: SeasonIndex,
    index_type: IndexType,
    trigger: float,
    exit: float,
    limit_cents: float,
    min_seasons: int,
) -> BacktestFigures:
    """Raises `invalid_cover` for a bad cover and `insufficient_history` under `min_seasons`."""
    validate_cover(index_type, trigger, exit, limit_cents)
    seasons_used = len(season_index.seasons)
    require_history(seasons_used, min_seasons)
    values = season_index.values
    payouts = payout_amounts(index_type, values, trigger, exit, limit_cents)
    seasons_paying = int(np.count_nonzero(paying(index_type, values, trigger)))
    max_payout = float(payouts.max())
    return BacktestFigures(
        seasons=season_index.seasons,
        index_values=values,
        payouts=payouts,
        seasons_excluded=season_index.excluded,
        trigger_frequency=seasons_paying / seasons_used,
        burn_cost=float(payouts.mean()),
        max_payout=max_payout,
        max_payout_season=season_index.seasons[int(payouts.argmax())] if max_payout > 0 else None,
        trend=trend(season_index.seasons, values),
    )
