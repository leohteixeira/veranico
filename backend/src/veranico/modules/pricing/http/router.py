"""Routes of `pricing`: per-cell metrics and the seasonal series of a point.

Public reference data, no workspace cookie. Path, method, operation id, parameters and
schemas are frozen by the OpenAPI contract. `GET /regions/{id}/cells` is still the stub of
the foundation milestone (plan 02 Task 13 replaces it).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path

from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.pricing.application.service import check_index
from veranico.modules.pricing.contracts import CellGrid, PricingFacade, SeasonSeries
from veranico.modules.pricing.http.schemas import IndexQuery
from veranico.shared.kernel.errors import NotImplementedYetError
from veranico.shared.kernel.money import Money


def build_router(facade: PricingFacade, climate: ClimateFacade) -> APIRouter:
    """`climate` resolves the point of `GET /weather/seasons` to its dataset."""
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
        check_index(index)  # before the history is loaded: it may be fetched on first use
        dataset = await climate.ensure_history(lat, lon)
        limit = Money(amount_cents=limit_cents) if limit_cents is not None else None
        return await facade.season_series(dataset.dataset_id, index, limit)

    return router
