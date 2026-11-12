"""From the domain's float figures to the contract models (SPEC 5.7).

This is the only place that calls the rounding functions, and it rounds each figure once
from its float value. The one exception is `gap_to_burn_cost`: the integer difference of
the two rounded figures, so the three numbers a reader sees reconcile.

Texts are codes with parameters (contracts conventions). The eight codes of `pricing`:

| Code                           | Parameters                                          |
|--------------------------------|-----------------------------------------------------|
| `warning.trend_significant`    | `slope_per_decade` (float), `direction` (str)       |
| `warning.seasons_excluded`     | `count` (int), `seasons` (str, comma-separated)     |
| `assumption.index_type`        | `index_type` (str)                                  |
| `assumption.window`            | `start`, `end` (str, MM-DD)                         |
| `assumption.seasons_used`      | `seasons_used`, `first_season`, `last_season` (int) |
| `assumption.simulation_method` | `method` (str), `n`, `seed` (int)                   |
| `assumption.loads`             | `risk_load_rate`, `expense_load_rate` (six places)  |
| `assumption.data_source`       | `source` (str)                                      |
"""

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from veranico.modules.climate.contracts import Region
from veranico.modules.pricing.contracts import (
    BacktestResult,
    CellGrid,
    CellMetricRequest,
    CoverDefinition,
    ExtremeSeason,
    IndexDefinition,
    Premium,
    PricedCover,
    SeasonResult,
    SeasonSeries,
    SimulationResult,
    Trend,
)
from veranico.modules.pricing.domain.backtest import BacktestFigures
from veranico.modules.pricing.domain.extremes import ExtremeFigures
from veranico.modules.pricing.domain.index import SeasonIndex
from veranico.modules.pricing.domain.premium import PremiumFigures
from veranico.modules.pricing.domain.rounding import (
    cents_difference,
    to_cents,
    to_fraction,
    to_rate,
    to_tenth,
)
from veranico.modules.pricing.domain.simulation import SimulationFigures
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money


def money(cents: float) -> Money:
    return Money(amount_cents=to_cents(cents))


def cell_grid(
    request: CellMetricRequest,
    region: Region,
    grid: npt.NDArray[np.float64],
    breaks: Sequence[float],
    seasons: Sequence[int],
    cells_paying: int | None,
    suggested_season: int | None,
) -> CellGrid:
    """`grid` is [row, col] with row 0 in the north; it leaves row-major, NaN as `None`."""
    return CellGrid(
        region_id=region.region_id,
        metric=request.metric,
        nx=region.nx,
        ny=region.ny,
        north=region.north,
        west=region.west,
        step_deg=region.step_deg,
        values=[None if math.isnan(value) else to_fraction(value) for value in grid.ravel()],
        breaks=[to_fraction(edge) for edge in breaks],
        seasons=list(seasons),
        cells_paying=cells_paying,
        suggested_season=suggested_season,
    )


def season_results(
    seasons: Sequence[int], index_values: Sequence[float], payouts: Sequence[float] | None
) -> list[SeasonResult]:
    """One entry per usable season, ascending; `payout` is `None` when no limit was given."""
    return [
        SeasonResult(
            season=season,
            index_value=to_tenth(float(index_values[position])),
            payout=money(float(payouts[position])) if payouts is not None else None,
        )
        for position, season in enumerate(seasons)
    ]


def season_series(
    dataset_id: DatasetId,
    index: IndexDefinition,
    season_index: SeasonIndex,
    payouts: Sequence[float] | None,
) -> SeasonSeries:
    return SeasonSeries(
        dataset_id=dataset_id,
        index=index,
        seasons=season_results(season_index.seasons, season_index.values.tolist(), payouts),
        seasons_excluded=list(season_index.excluded),
    )


def backtest_result(
    dataset_id: DatasetId, cover: CoverDefinition, figures: BacktestFigures
) -> BacktestResult:
    trend = figures.trend
    warnings: list[Coded] = []
    if trend.significant:
        warnings.append(
            Coded(
                code="warning.trend_significant",
                params={
                    "slope_per_decade": to_tenth(trend.slope_per_decade),
                    "direction": "increasing" if trend.slope_per_decade > 0 else "decreasing",
                },
            )
        )
    if figures.seasons_excluded:
        warnings.append(
            Coded(
                code="warning.seasons_excluded",
                params={
                    "count": len(figures.seasons_excluded),
                    "seasons": ", ".join(str(season) for season in figures.seasons_excluded),
                },
            )
        )
    return BacktestResult(
        dataset_id=dataset_id,
        cover=cover,
        seasons=season_results(
            figures.seasons, figures.index_values.tolist(), figures.payouts.tolist()
        ),
        seasons_used=figures.seasons_used,
        seasons_excluded=list(figures.seasons_excluded),
        trigger_frequency=to_rate(figures.trigger_frequency),
        burn_cost=money(figures.burn_cost),
        max_payout=money(figures.max_payout),
        max_payout_season=figures.max_payout_season,
        trend=Trend(
            slope_per_decade=to_tenth(trend.slope_per_decade),
            p_value=to_rate(trend.p_value),
            significant=trend.significant,
        ),
        warnings=warnings,
    )


def simulation_result(figures: SimulationFigures, burn_cost: Money) -> SimulationResult:
    expected_loss = money(figures.expected_loss)
    return SimulationResult(
        method=figures.method,
        n=figures.n,
        seed=figures.seed,
        expected_loss=expected_loss,
        std_dev=money(figures.std_dev),
        probability_of_payout=to_rate(figures.probability_of_payout),
        payout_1_in_10=money(figures.payout_1_in_10),
        payout_1_in_100=money(figures.payout_1_in_100),
        # Both operands are already rounded: the difference of the two figures shown.
        gap_to_burn_cost=Money(
            amount_cents=cents_difference(expected_loss.amount_cents, burn_cost.amount_cents)
        ),
    )


def premium_result(figures: PremiumFigures, risk_load: float, expense_load: float) -> Premium:
    return Premium(
        premium=money(figures.premium),
        rate_on_line=to_rate(figures.rate_on_line),  # from the unrounded premium
        risk_load=to_rate(risk_load),
        expense_load=to_rate(expense_load),
    )


def priced_cover(
    backtest: BacktestResult, simulation: SimulationResult, premium: Premium, source: str
) -> PricedCover:
    index = backtest.cover.index
    return PricedCover(
        backtest=backtest,
        simulation=simulation,
        premium=premium,
        assumptions=[
            Coded(code="assumption.index_type", params={"index_type": index.index_type}),
            Coded(
                code="assumption.window",
                params={"start": index.window.start, "end": index.window.end},
            ),
            Coded(
                code="assumption.seasons_used",
                params={
                    "seasons_used": backtest.seasons_used,
                    "first_season": backtest.seasons[0].season,
                    "last_season": backtest.seasons[-1].season,
                },
            ),
            Coded(
                code="assumption.simulation_method",
                params={"method": simulation.method, "n": simulation.n, "seed": simulation.seed},
            ),
            Coded(
                code="assumption.loads",
                params={
                    "risk_load_rate": premium.risk_load,
                    "expense_load_rate": premium.expense_load,
                },
            ),
            Coded(code="assumption.data_source", params={"source": source}),
        ],
    )


def extreme_seasons(figures: Sequence[ExtremeFigures]) -> list[ExtremeSeason]:
    return [
        ExtremeSeason(
            season=item.season,
            index_value=to_tenth(item.index_value),
            rank=item.rank,
            return_period_years=to_tenth(item.return_period_years),
        )
        for item in figures
    ]
