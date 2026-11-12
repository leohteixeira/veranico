"""Public surface of `pricing`: index, backtest, simulation, premium, per-cell metrics."""

from typing import Literal, Protocol

from pydantic import BaseModel

from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money, Rate

IndexType = Literal["rainfall_below", "dry_spell_above"]


class Window(BaseModel, frozen=True):
    start: str  # MM-DD
    end: str  # MM-DD; may be earlier than start (crosses the year)


class IndexDefinition(BaseModel, frozen=True):
    index_type: IndexType
    window: Window
    trigger: float  # mm or days
    exit: float  # rainfall_below: exit < trigger; dry_spell_above: exit > trigger


class CoverDefinition(BaseModel, frozen=True):
    index: IndexDefinition
    limit: Money


class SeasonResult(BaseModel, frozen=True):
    season: int  # start year
    index_value: float
    payout: Money | None  # None when no limit was given


class Trend(BaseModel, frozen=True):
    slope_per_decade: float
    p_value: Rate
    significant: bool  # p < 0.05


class BacktestResult(BaseModel, frozen=True):
    dataset_id: DatasetId
    cover: CoverDefinition
    seasons: list[SeasonResult]
    seasons_used: int
    seasons_excluded: list[int]
    trigger_frequency: Rate
    burn_cost: Money
    max_payout: Money
    max_payout_season: int | None
    trend: Trend
    warnings: list[Coded]  # warning.trend_significant, warning.seasons_excluded


class SimulationOptions(BaseModel, frozen=True):
    n: int = 100_000
    seed: int = 42


class SimulationResult(BaseModel, frozen=True):
    method: Literal["gamma_mle", "bootstrap"]
    n: int
    seed: int
    expected_loss: Money
    std_dev: Money
    probability_of_payout: Rate
    payout_1_in_10: Money
    payout_1_in_100: Money
    gap_to_burn_cost: Money  # simulated expected loss minus historical; may be negative


class Premium(BaseModel, frozen=True):
    premium: Money
    rate_on_line: Rate
    risk_load: Rate
    expense_load: Rate


class PricedCover(BaseModel, frozen=True):
    backtest: BacktestResult
    simulation: SimulationResult
    premium: Premium
    assumptions: list[
        Coded
    ]  # assumption.index_type, .window, .seasons_used, .simulation_method, .loads, .data_source


class SeasonSeries(BaseModel, frozen=True):
    dataset_id: DatasetId
    index: IndexDefinition
    seasons: list[SeasonResult]
    seasons_excluded: list[int]


class ExtremeSeason(BaseModel, frozen=True):
    season: int
    index_value: float
    rank: int
    return_period_years: float  # empirical, (n + 1) / rank


class CellMetricRequest(BaseModel, frozen=True):
    region_id: str
    metric: Literal["trigger_frequency", "season_anomaly"]
    index: IndexDefinition
    season: int | None = None  # required for season_anomaly


class CellGrid(BaseModel, frozen=True):
    region_id: str
    metric: Literal["trigger_frequency", "season_anomaly"]
    nx: int
    ny: int
    north: float
    west: float
    step_deg: float
    values: list[
        float | None
    ]  # row-major, north to south, west to east; a fraction for both metrics
    breaks: list[float]  # class boundaries for the legend
    seasons: list[int]
    cells_paying: int | None  # season_anomaly only
    suggested_season: int | None  # season most evenly split between dry and wet cells


class PricingFacade(Protocol):
    async def backtest(self, dataset_id: DatasetId, cover: CoverDefinition) -> BacktestResult: ...
    async def price(
        self, dataset_id: DatasetId, cover: CoverDefinition, options: SimulationOptions
    ) -> PricedCover: ...
    async def season_series(
        self, dataset_id: DatasetId, index: IndexDefinition, limit: Money | None
    ) -> SeasonSeries: ...
    async def extreme_seasons(
        self, dataset_id: DatasetId, index_type: IndexType, window: Window, top_n: int
    ) -> list[ExtremeSeason]: ...
    async def cell_metrics(self, request: CellMetricRequest) -> CellGrid: ...
