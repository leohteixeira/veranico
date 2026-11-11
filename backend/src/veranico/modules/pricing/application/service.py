"""Use cases of `pricing`: the implementation of `PricingFacade`.

Each use case reads the daily series through `ClimateFacade`, calls the pure domain and
maps the float figures to the contract models (`mapping.py`). Loads, simulation defaults
and the minimum number of seasons come from the `pricing` settings group.
"""

from veranico.modules.climate.contracts import ClimateFacade, DailySeries
from veranico.modules.pricing.application import mapping
from veranico.modules.pricing.contracts import (
    BacktestResult,
    CellGrid,
    CellMetricRequest,
    CoverDefinition,
    ExtremeSeason,
    IndexDefinition,
    IndexType,
    PricedCover,
    SeasonSeries,
    SimulationOptions,
    Window,
)
from veranico.modules.pricing.domain import backtest as backtest_rules
from veranico.modules.pricing.domain import extremes, payout, premium, simulation
from veranico.modules.pricing.domain.backtest import BacktestFigures
from veranico.modules.pricing.domain.index import SeasonIndex, index_series
from veranico.modules.pricing.domain.seasons import parse_window
from veranico.shared.infrastructure.settings import PricingSettings
from veranico.shared.kernel.errors import InvalidArgumentsError
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money

# A simulation draws `n` float64 values at once. The bound keeps one request from asking
# for gigabytes of memory; it is ten times the default size.
MAX_SIMULATION_N = 1_000_000


def check_index(index: IndexDefinition) -> None:
    """Raises `invalid_cover` for a bad window or an exit on the wrong side of the trigger."""
    parse_window(index.window.start, index.window.end)
    payout.validate_index(index.index_type, index.trigger, index.exit)


class PricingService:
    def __init__(self, *, climate: ClimateFacade, settings: PricingSettings) -> None:
        self._climate = climate
        self._settings = settings

    async def backtest(self, dataset_id: DatasetId, cover: CoverDefinition) -> BacktestResult:
        _check_cover(cover)
        series = await self._climate.daily_series(dataset_id)
        return mapping.backtest_result(dataset_id, cover, self._backtest(series, cover))

    async def price(
        self, dataset_id: DatasetId, cover: CoverDefinition, options: SimulationOptions
    ) -> PricedCover:
        _check_cover(cover)
        n, seed = self._simulation_options(options)
        series = await self._climate.daily_series(dataset_id)
        index = cover.index
        limit_cents = cover.limit.amount_cents
        history = self._backtest(series, cover)
        simulated = simulation.simulate(
            index.index_type, history.index_values, index.trigger, index.exit, limit_cents, n, seed
        )
        risk_load, expense_load = self._settings.risk_load, self._settings.expense_load
        premium_figures = premium.premium(
            simulated.expected_loss, simulated.std_dev, risk_load, expense_load, limit_cents
        )
        backtest_result = mapping.backtest_result(dataset_id, cover, history)
        return mapping.priced_cover(
            backtest_result,
            mapping.simulation_result(simulated, backtest_result.burn_cost),
            mapping.premium_result(premium_figures, risk_load, expense_load),
            series.dataset.source,
        )

    async def season_series(
        self, dataset_id: DatasetId, index: IndexDefinition, limit: Money | None
    ) -> SeasonSeries:
        if limit is None:
            check_index(index)
        else:
            _check_cover(CoverDefinition(index=index, limit=limit))
        series = await self._climate.daily_series(dataset_id)
        season_index = self._season_index(series, index.index_type, index.window)
        payouts = None
        if limit is not None:
            payouts = payout.payout_amounts(
                index.index_type,
                season_index.values,
                index.trigger,
                index.exit,
                limit.amount_cents,
            ).tolist()
        return mapping.season_series(dataset_id, index, season_index, payouts)

    async def extreme_seasons(
        self, dataset_id: DatasetId, index_type: IndexType, window: Window, top_n: int
    ) -> list[ExtremeSeason]:
        parse_window(window.start, window.end)
        if top_n < 1:
            raise InvalidArgumentsError("top_n must be at least 1")
        series = await self._climate.daily_series(dataset_id)
        season_index = self._season_index(series, index_type, window)
        return mapping.extreme_seasons(
            extremes.extreme_seasons(
                index_type, season_index.seasons, season_index.values.tolist(), top_n
            )
        )

    async def cell_metrics(self, request: CellMetricRequest) -> CellGrid:
        raise NotImplementedError  # plan 02 Task 13

    def _season_index(
        self, series: DailySeries, index_type: IndexType, window: Window
    ) -> SeasonIndex:
        """The index per usable season; `insufficient_history` under the configured minimum."""
        bounds = parse_window(window.start, window.end)
        season_index = index_series(series.dates, series.precipitation_mm, index_type, bounds)
        backtest_rules.require_history(len(season_index.seasons), self._settings.min_seasons)
        return season_index

    def _backtest(self, series: DailySeries, cover: CoverDefinition) -> BacktestFigures:
        index = cover.index
        return backtest_rules.backtest(
            self._season_index(series, index.index_type, index.window),
            index.index_type,
            index.trigger,
            index.exit,
            cover.limit.amount_cents,
            self._settings.min_seasons,
        )

    def _simulation_options(self, options: SimulationOptions) -> tuple[int, int]:
        """A field the caller did not set takes the configured default (SPEC 5.5)."""
        given = options.model_fields_set
        n = options.n if "n" in given else self._settings.simulation_n
        seed = options.seed if "seed" in given else self._settings.simulation_seed
        if not 1 <= n <= MAX_SIMULATION_N:
            raise InvalidArgumentsError(f"n must be between 1 and {MAX_SIMULATION_N}")
        return n, seed


def _check_cover(cover: CoverDefinition) -> None:
    check_index(cover.index)
    payout.validate_cover(
        cover.index.index_type, cover.index.trigger, cover.index.exit, cover.limit.amount_cents
    )
