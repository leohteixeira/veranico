"""A FastAPI application for a module's API tests, without the other modules."""

from collections.abc import Sequence

from fastapi import APIRouter, FastAPI

from tests.fakes.access import FakeAccessFacade
from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.http_auth import AccessPort, install_auth
from veranico.shared.infrastructure.problems import PROBLEM_RESPONSES, install_problem_handlers
from veranico.shared.infrastructure.settings import Settings

API_PREFIX = "/api/v1"


def build_test_app(
    routers: Sequence[APIRouter],
    access: AccessPort | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """Mount the routers under `/api/v1` as the real application does.

    The problem handlers are installed and the authentication dependencies are bound to
    `access` (a new `FakeAccessFacade` when none is given). The default settings turn the
    service identity check off; pass settings to test it.
    """
    app = FastAPI(responses=PROBLEM_RESPONSES)
    install_problem_handlers(app)
    install_auth(
        app,
        access=access if access is not None else FakeAccessFacade(),
        settings=settings if settings is not None else settings_for_tests(),
    )
    for router in routers:
        app.include_router(router, prefix=API_PREFIX)
    return app
