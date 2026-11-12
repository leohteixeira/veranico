"""Routes of `climate`: the showcase regions. Public reference data, no workspace cookie."""

from fastapi import APIRouter

from veranico.modules.climate.contracts import ClimateFacade, Region


def build_router(facade: ClimateFacade) -> APIRouter:
    router = APIRouter(tags=["climate"])

    @router.get("/regions", operation_id="list_regions")
    async def list_regions() -> list[Region]:
        return await facade.regions()

    return router
