"""Wiring of `pricing`. Only `bootstrap.py` imports this file.

Stub of the foundation milestone: plan 02 replaces the body of `build` and keeps its signature.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter

from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.contracts import (
    BacktestResult,
    CellGrid,
    CellMetricRequest,
    CoverDefinition,
    ExtremeSeason,
    IndexDefinition,
    IndexType,
    PricedCover,
    PricingFacade,
    SeasonSeries,
    SimulationOptions,
    Window,
)
from veranico.modules.pricing.http.router import build_router
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.ids import DatasetId
from veranico.shared.kernel.money import Money


@dataclass(frozen=True, kw_only=True)
class PricingDeps:
    settings: Settings
    climate: ClimateFacade


@dataclass(frozen=True, kw_only=True)
class PricingModule:
    facade: PricingFacade
    routers: Sequence[APIRouter]


class _StubPricingFacade:
    async def backtest(self, dataset_id: DatasetId, cover: CoverDefinition) -> BacktestResult:
        raise NotImplementedError

    async def price(
        self, dataset_id: DatasetId, cover: CoverDefinition, options: SimulationOptions
    ) -> PricedCover:
        raise NotImplementedError

    async def season_series(
        self, dataset_id: DatasetId, index: IndexDefinition, limit: Money | None
    ) -> SeasonSeries:
        raise NotImplementedError

    async def extreme_seasons(
        self, dataset_id: DatasetId, index_type: IndexType, window: Window, top_n: int
    ) -> list[ExtremeSeason]:
        raise NotImplementedError

    async def cell_metrics(self, request: CellMetricRequest) -> CellGrid:
        raise NotImplementedError


def build(deps: PricingDeps) -> PricingModule:
    facade = _StubPricingFacade()
    return PricingModule(facade=facade, routers=(build_router(facade),))
