"""Routes of `climate`: the showcase regions. Public reference data, no workspace cookie.

Stub of the foundation milestone: path, method, operation id and schemas are final.
Plan 01 replaces the handler body.
"""

from fastapi import APIRouter

from veranico.modules.climate.contracts import ClimateFacade, Region
from veranico.shared.kernel.errors import NotImplementedYetError


def build_router(facade: ClimateFacade) -> APIRouter:
    router = APIRouter(tags=["climate"])

    @router.get("/regions", operation_id="list_regions")
    async def list_regions() -> list[Region]:
        raise NotImplementedYetError

    return router
