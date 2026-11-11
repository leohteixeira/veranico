"""Who is calling: the FastAPI dependencies every router uses.

| Dependency                 | Caller                                                        |
|----------------------------|---------------------------------------------------------------|
| `browser_principal`        | the web application, by the workspace cookie `vr_ws`          |
| `api_key_principal`        | the public broker API, by `Authorization: Bearer <key>`       |
| `any_principal`            | either: a bearer when the header is present, else the cookie  |
| `visitor_ref`              | the visitor behind a request, as a salted hash, never an address |
| `require_service_identity` | Cloud Tasks, Cloud Scheduler or the in-process relay           |

The dependencies find the `access` facade and the settings in application state, which
`install_auth` sets from the composition root (and from test applications). Shared code
imports no module, so the part of the facade used here is declared as `AccessPort`.

Privacy: the client address and the allowance code are handed to `AccessPort.visitor` and
then dropped. They appear in no log line, span attribute or exception.
"""

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyCookie, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.errors import ForbiddenError
from veranico.shared.kernel.principal import Principal

WORKSPACE_COOKIE = "vr_ws"
ALLOWANCE_CODE_HEADER = "Veranico-Allowance-Code"

IdTokenVerifier = Callable[[str, str], Mapping[str, Any]]
"""`(token, audience) -> claims`; raises when the token is not valid for that audience."""


class AccessPort(Protocol):
    """The methods of `AccessFacade` this file calls."""

    def visitor(self, client_ip: str, code: str | None) -> object: ...
    async def open_workspace(self, cookie: str | None) -> tuple[Principal, str | None]: ...
    async def authenticate_api_key(self, bearer: str) -> Principal: ...
    async def check_rate(self, principal: Principal) -> None: ...


@dataclass(frozen=True)
class AuthContext:
    access: AccessPort
    settings: Settings
    verify_id_token: IdTokenVerifier


def verify_google_id_token(token: str, audience: str) -> Mapping[str, Any]:
    """Verify a Google-signed ID token: signature, expiry, audience and issuer.

    `verify_oauth2_token` fetches Google's public certificates on every call. The two
    internal routes are called a few times per delivery, so no cache is kept.
    """
    claims: Mapping[str, Any] = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]  # google-auth leaves this function unannotated
        token, google_requests.Request(), audience
    )
    return claims


def install_auth(
    app: FastAPI,
    *,
    access: AccessPort,
    settings: Settings,
    verify_id_token: IdTokenVerifier = verify_google_id_token,
) -> None:
    """Bind the dependencies of this file to a facade and settings.

    Call it while the application is being built: it also adds the middleware that sends
    a newly issued workspace cookie.
    """
    app.add_middleware(WorkspaceCookieMiddleware, settings=settings)
    app.state.auth = AuthContext(access=access, settings=settings, verify_id_token=verify_id_token)


def _context(request: Request) -> AuthContext:
    context = request.app.state.auth
    assert isinstance(context, AuthContext)
    return context


# The scheme objects only describe the credentials in the OpenAPI document. They never
# reject a request themselves (`auto_error=False`): the dependencies below read the raw
# header or cookie, so a malformed credential is `forbidden` and not a silent fallback.
_cookie_scheme = APIKeyCookie(
    name=WORKSPACE_COOKIE,
    scheme_name="WorkspaceCookie",
    description="Anonymous workspace cookie, set by the service on the first web request.",
    auto_error=False,
)
_api_key_scheme = HTTPBearer(
    scheme_name="ApiKey",
    description="API key of a workspace, created from the interface.",
    auto_error=False,
)
_service_scheme = HTTPBearer(
    scheme_name="ServiceIdentity",
    description="Google-signed ID token of the invoker service account.",
    auto_error=False,
)


def _bearer(request: Request) -> str:
    """Return the bearer credential; a missing or malformed header is `forbidden`."""
    scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
    credential = credential.strip()
    if scheme.lower() != "bearer" or not credential:
        raise ForbiddenError
    return credential


async def _from_cookie(request: Request) -> Principal:
    principal, new_cookie = await _context(request).access.open_workspace(
        request.cookies.get(WORKSPACE_COOKIE)
    )
    if new_cookie is not None:
        # Sent by `WorkspaceCookieMiddleware` on whatever response this request gets.
        request.state.new_workspace_cookie = new_cookie
    return principal


class WorkspaceCookieMiddleware:
    """Set a newly issued workspace cookie on the response, whatever kind it is.

    FastAPI copies a cookie set by a dependency only onto a response it builds itself from
    a returned value. A problem document, a stream or any `Response` the handler returns
    would lose it, and the visitor's next request would open a second workspace. So the
    dependency leaves the cookie in the request state and this middleware adds the header
    when the response starts.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._max_age = settings.access.workspace_ttl_days * 24 * 60 * 60
        self._secure = settings.environment != "development"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        state = scope.setdefault("state", {})

        async def send_with_cookie(message: Message) -> None:
            cookie = state.get("new_workspace_cookie")
            if message["type"] == "http.response.start" and cookie is not None:
                MutableHeaders(scope=message).append("Set-Cookie", self._header(cookie))
            await send(message)

        await self._app(scope, receive, send_with_cookie)

    def _header(self, value: str) -> str:
        carrier = Response()
        carrier.set_cookie(
            WORKSPACE_COOKIE,
            value,
            max_age=self._max_age,
            path="/",
            httponly=True,
            samesite="lax",
            secure=self._secure,
        )
        return carrier.headers["set-cookie"]


async def _from_api_key(request: Request) -> Principal:
    context = _context(request)
    principal = await context.access.authenticate_api_key(_bearer(request))
    await context.access.check_rate(principal)
    return principal


async def browser_principal(
    request: Request,
    _documented: Annotated[object, Depends(_cookie_scheme)],
) -> Principal:
    """The workspace of the browser. An `Authorization` header is ignored."""
    return await _from_cookie(request)


async def api_key_principal(
    request: Request,
    _documented: Annotated[object, Depends(_api_key_scheme)],
) -> Principal:
    """The workspace of an API key, after the per-key rate limit."""
    return await _from_api_key(request)


async def any_principal(
    request: Request,
    _documented_key: Annotated[object, Depends(_api_key_scheme)],
    _documented_cookie: Annotated[object, Depends(_cookie_scheme)],
) -> Principal:
    """A bearer when the header is present, and then never the cookie; else the cookie."""
    if "Authorization" in request.headers:
        return await _from_api_key(request)
    return await _from_cookie(request)


def client_address(request: Request) -> str:
    """The address of the client as the platform saw it.

    Cloud Run's front end appends the address of the peer that connected to it to
    `X-Forwarded-For`, after anything the client sent in that header. Only that last
    entry is trustworthy: every earlier entry is supplied by the client. Without the
    header (a direct connection in development) the socket peer is the client.
    """
    forwarded = request.headers.get("X-Forwarded-For", "").rsplit(",", 1)[-1].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client is not None else "unknown"


def visitor_ref(
    request: Request,
    allowance_code: Annotated[
        str | None,
        Header(
            alias=ALLOWANCE_CODE_HEADER,
            description="The code the visitor arrived with, when there was one.",
        ),
    ] = None,
) -> object:
    """The `VisitorRef` of the caller. The address and the code go no further than here."""
    return _context(request).access.visitor(client_address(request), allowance_code)


async def require_service_identity(
    request: Request,
    _documented: Annotated[object, Depends(_service_scheme)],
) -> None:
    """Accept only the service identity the internal authentication mode names."""
    context = _context(request)
    delivery = context.settings.delivery
    if delivery.internal_auth == "disabled":
        return
    credential = _bearer(request)
    if delivery.internal_auth == "token":
        expected = delivery.internal_token.get_secret_value() if delivery.internal_token else ""
        if not expected or not hmac.compare_digest(credential.encode(), expected.encode()):
            raise ForbiddenError
        return
    if delivery.oidc_audience is None or delivery.oidc_invoker_email is None:
        raise ForbiddenError
    try:
        claims = await run_in_threadpool(
            context.verify_id_token, credential, delivery.oidc_audience
        )
    except Exception:
        # Any verification failure is the same answer; the reason is not disclosed.
        raise ForbiddenError from None
    if (
        claims.get("email") != delivery.oidc_invoker_email
        or claims.get("email_verified") is not True
    ):
        raise ForbiddenError
