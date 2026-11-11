"""Routes of `pricing`: per-cell metrics and the seasonal series of a point.

Public reference data, no workspace cookie. Stub of the foundation milestone: path,
method, operation id, parameters and schemas are final. Plan 02 replaces the handler bodies.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path

from veranico.modules.pricing.contracts import CellGrid, PricingFacade, SeasonSeries
from veranico.modules.pricing.http.schemas import IndexQuery
from veranico.shared.kernel.errors import NotImplementedYetError


def build_router(facade: PricingFacade) -> APIRouter:
    router = APIRouter(tags=["pricing"])

    @router.get("/regions/{id}/cells", operation_id="get_region_cells")
    async def get_region_cells(
        region_id: Annotated[str, Path(alias="id")],
        metric: Literal["trigger_frequency", "season_anomaly"],
        index: IndexQuery,
        season: int | None = None,
    ) -> CellGrid:
        raise NotImplementedYetError

    @router.get("/weather/seasons", operation_id="get_season_series")
    async def get_season_series(
        lat: float,
        lon: float,
        index: IndexQuery,
        limit_cents: int | None = None,
    ) -> SeasonSeries:
        raise NotImplementedYetError

    return router
