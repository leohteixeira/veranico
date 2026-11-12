"""In-memory fake of `PricingFacade`: canned figures, the contract's errors, no I/O.

A dataset exists when the test registered it with `add_dataset`, or when the fake was given
a climate facade that knows it. Regions for `cell_metrics` are registered with `add_region`.
The figures come from `builders.py`: integer centavos derived from the limit, identical for
identical input. `calls` lists every call received, in order.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tests.fakes import builders
from tests.fakes.access import Call
from veranico.modules.climate.contracts import ClimateFacade, Region
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
from veranico.shared.kernel.errors import (
    DatasetNotFoundError,
    InsufficientHistoryError,
    InvalidArgumentsError,
    InvalidCoverError,
)
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money

MIN_SEASONS = 20


@dataclass(frozen=True)
class _Dataset:
    first_season: int
    seasons: int
    seasons_excluded: tuple[int, ...]
    trend_significant: bool
    source: builders.Source


class FakePricingFacade:
    def __init__(self, climate: ClimateFacade | None = None) -> None:
        self._climate = climate
        self._datasets: dict[DatasetId, _Dataset] = {}
        self._regions: dict[str, Region] = {}
        self.calls: list[Call] = []

    # What a test registers

    def add_dataset(
        self,
        dataset_id: DatasetId,
        *,
        first_season: int = builders.FIRST_YEAR,
        seasons: int = builders.SEASONS,
        seasons_excluded: Sequence[int] = (),
        trend_significant: bool = False,
        source: builders.Source = "synthetic",
    ) -> None:
        self._datasets[dataset_id] = _Dataset(
            first_season, seasons, tuple(seasons_excluded), trend_significant, source
        )

    def add_region(self, region: Region) -> None:
        self._regions[region.region_id] = region

    # PricingFacade

    async def backtest(self, dataset_id: DatasetId, cover: CoverDefinition) -> BacktestResult:
        self.calls.append(("backtest", (dataset_id, cover)))
        _validate_cover(cover)
        dataset = await self._usable(dataset_id)
        return builders.backtest_result(
            cover,
            dataset_id=dataset_id,
            first_season=dataset.first_season,
            seasons=dataset.seasons,
            seasons_excluded=dataset.seasons_excluded,
            trend_significant=dataset.trend_significant,
        )

    async def price(
        self, dataset_id: DatasetId, cover: CoverDefinition, options: SimulationOptions
    ) -> PricedCover:
        self.calls.append(("price", (dataset_id, cover, options)))
        _validate_cover(cover)
        if options.n < 1:
            raise InvalidArgumentsError("n must be positive")
        dataset = await self._usable(dataset_id)
        return builders.priced_cover(
            cover,
            dataset_id=dataset_id,
            options=options,
            first_season=dataset.first_season,
            seasons=dataset.seasons,
            seasons_excluded=dataset.seasons_excluded,
            trend_significant=dataset.trend_significant,
            source=dataset.source,
        )

    async def season_series(
        self, dataset_id: DatasetId, index: IndexDefinition, limit: Money | None
    ) -> SeasonSeries:
        self.calls.append(("season_series", (dataset_id, index, limit)))
        _validate_index(index)
        if limit is not None and limit.amount_cents <= 0:
            raise InvalidCoverError("the limit must be positive")
        dataset = await self._usable(dataset_id)
        return SeasonSeries(
            dataset_id=dataset_id,
            index=index,
            seasons=builders.season_results(
                index,
                limit.amount_cents if limit is not None else None,
                first_season=dataset.first_season,
                seasons=dataset.seasons,
                seasons_excluded=dataset.seasons_excluded,
            ),
            seasons_excluded=sorted(dataset.seasons_excluded),
        )

    async def extreme_seasons(
        self, dataset_id: DatasetId, index_type: IndexType, window: Window, top_n: int
    ) -> list[ExtremeSeason]:
        self.calls.append(("extreme_seasons", (dataset_id, index_type, window, top_n)))
        _validate_window(window)
        if not 1 <= top_n <= 10:
            raise InvalidArgumentsError("top_n must be between 1 and 10")
        dataset = await self._usable(dataset_id)
        used = [
            dataset.first_season + position
            for position in range(dataset.seasons)
            if dataset.first_season + position not in dataset.seasons_excluded
        ]
        below = index_type == "rainfall_below"
        return [
            ExtremeSeason(
                season=season,
                index_value=float(100 + 25 * rank) if below else float(60 - 3 * rank),
                rank=rank,
                return_period_years=(len(used) + 1) / rank,
            )
            for rank, season in enumerate(used[:top_n], start=1)
        ]

    async def cell_metrics(self, request: CellMetricRequest) -> CellGrid:
        self.calls.append(("cell_metrics", (request,)))
        _validate_index(request.index)
        if request.metric == "season_anomaly" and request.season is None:
            raise InvalidArgumentsError("season_anomaly needs a season")
        if request.region_id not in self._regions:
            raise DatasetNotFoundError
        area = self._regions[request.region_id]
        values: list[float | None] = [(cell % 5) / 5 for cell in range(area.nx * area.ny)]
        anomaly = request.metric == "season_anomaly"
        return CellGrid(
            region_id=area.region_id,
            metric=request.metric,
            nx=area.nx,
            ny=area.ny,
            north=area.north,
            west=area.west,
            step_deg=area.step_deg,
            values=values,
            breaks=[0.2, 0.4, 0.6, 0.8],
            seasons=list(range(builders.FIRST_YEAR, builders.FIRST_YEAR + builders.SEASONS)),
            cells_paying=sum(1 for value in values if value) if anomaly else None,
            suggested_season=builders.FIRST_YEAR,
        )

    # Internals

    async def _usable(self, dataset_id: DatasetId) -> _Dataset:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            if self._climate is None:
                raise DatasetNotFoundError
            described = await self._climate.describe(dataset_id)  # raises dataset_not_found
            dataset = _Dataset(
                first_season=described.first_year,
                seasons=described.last_year - described.first_year + 1,
                seasons_excluded=(),
                trend_significant=False,
                source=described.source,
            )
        if dataset.seasons - len(dataset.seasons_excluded) < MIN_SEASONS:
            raise InsufficientHistoryError
        return dataset


def _validate_window(window: Window) -> None:
    """A bound must be a real `MM-DD`; `02-29` is not one (the contract's "empty window")."""
    for bound in (window.start, window.end):
        try:
            month, day = bound.split("-")
            if len(month) != 2 or len(day) != 2:
                raise ValueError(bound)
            date(2001, int(month), int(day))  # 2001 is not a leap year
        except ValueError:
            raise InvalidCoverError("a window bound must be a real MM-DD date") from None


def _validate_index(index: IndexDefinition) -> None:
    _validate_window(index.window)
    below = index.index_type == "rainfall_below"
    if (below and not index.exit < index.trigger) or (not below and not index.exit > index.trigger):
        raise InvalidCoverError("the exit is on the wrong side of the trigger")


def _validate_cover(cover: CoverDefinition) -> None:
    _validate_index(cover.index)
    if cover.limit.amount_cents <= 0:
        raise InvalidCoverError("the limit must be positive")
