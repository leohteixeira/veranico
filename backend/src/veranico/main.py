"""The FastAPI application of one role.

Run it with `uvicorn veranico.main:create_app --factory`. `APP_ROLE=api` is the product;
`APP_ROLE=carrier` is the mock carrier. Both come from the same image.

Graceful shutdown. uvicorn stops accepting connections on SIGTERM, then waits for the open
ones, and only then runs the lifespan shutdown, so the lifespan is too late to end an open
stream. The lifespan startup therefore puts its own SIGTERM handler in front of uvicorn's:
it sets the shutdown event (readiness turns 503, `assistant` ends open streams with a final
event) and then calls the handler uvicorn installed. Run uvicorn with
`--timeout-graceful-shutdown` so a connection that does not end cannot hold the exit.
"""

import asyncio
import os
import signal
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import FrameType
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from veranico.bootstrap import Container, build_container
from veranico.shared.infrastructure import telemetry
from veranico.shared.infrastructure.http_auth import install_auth
from veranico.shared.infrastructure.problems import install_problem_handlers
from veranico.shared.infrastructure.settings import Settings

API_PREFIX = "/api/v1"
EMBED_PATH = "/embed/map"


class Health(BaseModel):
    status: Literal["ok"]


class Readiness(BaseModel):
    status: Literal["ready", "shutting_down"]


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    """Build the application. Settings come from the environment when none are given.

    A caller that needs the injection points of `build_container` (tests, the evaluation
    harness) builds the container itself and passes it.
    """
    if container is None:
        container = build_container(settings if settings is not None else Settings())
    settings = container.settings
    is_api = settings.app_role == "api"

    app = FastAPI(
        title="Veranico" if is_api else "Veranico mock carrier",
        version="1",
        lifespan=_lifespan(container),
    )
    install_problem_handlers(app)
    telemetry.setup_telemetry(settings, app)

    @app.get("/healthz", operation_id="healthz", tags=["health"])
    async def healthz() -> Health:
        return Health(status="ok")

    @app.get(
        "/readyz",
        operation_id="readyz",
        tags=["health"],
        responses={503: {"model": Readiness, "description": "The instance is shutting down."}},
    )
    async def readyz(response: Response) -> Readiness:
        if container.shutdown.is_set():
            response.status_code = 503
            return Readiness(status="shutting_down")
        return Readiness(status="ready")

    if is_api:
        assert container.access is not None
        install_auth(app, access=container.access.facade, settings=settings)
        for router in container.api_routers:
            app.include_router(router, prefix=API_PREFIX)
        app.add_middleware(_FrameAncestors, embed_origins=settings.frame_ancestors)
        if settings.frontend_dist.is_dir():
            app.frontend("/", directory=settings.frontend_dist, fallback="index.html")
    else:
        app.include_router(container.carriers.carrier_router)
    return app


def _lifespan(container: Container) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        restore = _announce_sigterm(container.shutdown)
        dispatcher = container.dispatcher
        try:
            start = getattr(dispatcher, "start", None)
            if start is not None:
                await start()
            try:
                yield
            finally:
                stop = getattr(dispatcher, "stop", None)
                if stop is not None:
                    await stop()
                await container.close()
                telemetry.shutdown()
        finally:
            restore()

    return lifespan


def _announce_sigterm(shutdown: asyncio.Event) -> Callable[[], None]:
    """Set `shutdown` when SIGTERM arrives, before the server starts waiting for connections.

    Returns the function that puts the previous handler back. `signal.signal` is used, not
    `loop.add_signal_handler`, which would displace the server's handler instead of running
    before it. Signal handlers can only be installed from the main thread; elsewhere (an
    application run by a test client in a worker thread) nothing is installed.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGTERM)

    def handle(signum: int, frame: FrameType | None) -> None:
        # Signal handlers run between two bytecodes of the main thread: hand the event to
        # the loop instead of touching asyncio state from here.
        loop.call_soon_threadsafe(shutdown.set)
        if callable(previous):
            previous(signum, frame)
        elif previous == signal.SIG_DFL:
            # No server handler to chain to: restore the default action and deliver again.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, handle)

    def restore() -> None:
        if signal.getsignal(signal.SIGTERM) is handle:
            signal.signal(signal.SIGTERM, previous)

    return restore


class _FrameAncestors:
    """Say which pages may frame a response: the configured origins for the embed, else nobody."""

    def __init__(self, app: ASGIApp, embed_origins: list[str]) -> None:
        self._app = app
        self._embed = f"frame-ancestors {' '.join(embed_origins) if embed_origins else "'none'"}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        is_embed = scope["path"].rstrip("/") == EMBED_PATH
        policy = self._embed if is_embed else "frame-ancestors 'none'"

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Content-Security-Policy"] = policy
            await send(message)

        await self._app(scope, receive, send_with_policy)
