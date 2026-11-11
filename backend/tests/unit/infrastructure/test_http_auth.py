import logging
from collections.abc import AsyncIterator, Mapping
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI, Response
from fastapi.responses import StreamingResponse

from tests.fakes.access import FakeAccessFacade
from tests.fakes.settings import settings_for_tests
from veranico.modules.access.contracts import VisitorRef
from veranico.shared.infrastructure.http_auth import (
    any_principal,
    api_key_principal,
    browser_principal,
    install_auth,
    require_service_identity,
    visitor_ref,
)
from veranico.shared.infrastructure.problems import install_problem_handlers
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.errors import AllowanceExhaustedError
from veranico.shared.kernel.principal import Principal

AUDIENCE = "https://veranico.example"
INVOKER = "invoker@example.iam.gserviceaccount.com"
CLIENT_ADDRESS = "203.0.113.77"


def fake_verifier(token: str, audience: str) -> Mapping[str, Any]:
    """Stands in for Google's verification: tokens are `<audience>|<email>|<verified>`."""
    token_audience, email, verified = token.split("|")
    if token_audience != audience:
        raise ValueError("wrong audience")
    return {"aud": token_audience, "email": email, "email_verified": verified == "true"}


def build(
    access: FakeAccessFacade | None = None, settings: Settings | None = None
) -> tuple[httpx.AsyncClient, FakeAccessFacade]:
    access = access or FakeAccessFacade()
    app = FastAPI()
    install_problem_handlers(app)
    install_auth(
        app,
        access=access,
        settings=settings or settings_for_tests(),
        verify_id_token=fake_verifier,
    )

    @app.get("/browser")
    async def browser(principal: Annotated[Principal, Depends(browser_principal)]) -> Principal:
        return principal

    @app.get("/key")
    async def key(principal: Annotated[Principal, Depends(api_key_principal)]) -> Principal:
        return principal

    @app.get("/any")
    async def either(principal: Annotated[Principal, Depends(any_principal)]) -> Principal:
        return principal

    @app.get("/visitor")
    async def visitor(ref: Annotated[VisitorRef, Depends(visitor_ref)]) -> VisitorRef:
        return ref

    @app.get("/browser/fails")
    async def fails(principal: Annotated[Principal, Depends(browser_principal)]) -> None:
        raise AllowanceExhaustedError

    @app.get("/browser/stream")
    async def stream(
        principal: Annotated[Principal, Depends(browser_principal)],
    ) -> StreamingResponse:
        async def events() -> AsyncIterator[bytes]:
            yield b"event: started\ndata: {}\n\n"
            yield b"event: done\ndata: {}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/browser/own-response")
    async def own_response(
        principal: Annotated[Principal, Depends(browser_principal)],
    ) -> Response:
        return Response(b"%PDF", media_type="application/pdf")

    @app.post("/internal", dependencies=[Depends(require_service_identity)])
    async def internal() -> dict[str, bool]:
        return {"accepted": True}

    transport = httpx.ASGITransport(app=app, client=(CLIENT_ADDRESS, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://test"), access


async def issue_key(client: httpx.AsyncClient, access: FakeAccessFacade) -> tuple[str, str]:
    """Open a workspace through the cookie route and issue a key for it."""
    first = await client.get("/browser")
    principal = Principal.model_validate(first.json())
    issued = await access.issue_api_key(principal)
    return issued.secret, principal.workspace_id


# browser_principal


async def test_first_request_gets_a_workspace_and_the_cookie_with_its_attributes() -> None:
    client, _ = build(
        settings=settings_for_tests(
            environment="production",
            delivery={
                "internal_auth": "oidc",
                "oidc_audience": AUDIENCE,
                "oidc_invoker_email": INVOKER,
            },
        )
    )

    response = await client.get("/browser")

    assert response.json() == {"workspace_id": "ws-1", "kind": "browser", "key_id": None}
    attributes = {part.strip().lower() for part in response.headers["set-cookie"].split(";")}
    assert "vr_ws=cookie-1" in attributes
    assert {"httponly", "samesite=lax", "path=/", "secure"} <= attributes
    assert f"max-age={14 * 24 * 60 * 60}" in attributes


@pytest.mark.parametrize(
    ("path", "status", "content_type"),
    [
        ("/browser/fails", 429, "application/problem+json"),
        ("/browser/stream", 200, "text/event-stream"),
        ("/browser/own-response", 200, "application/pdf"),
        ("/any", 200, "application/json"),
    ],
)
async def test_a_new_cookie_is_sent_on_every_kind_of_response(
    path: str, status: int, content_type: str
) -> None:
    client, _ = build()

    response = await client.get(path)

    assert response.status_code == status
    assert response.headers["content-type"].startswith(content_type)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("vr_ws=cookie-1;")
    assert "HttpOnly" in cookie
    assert response.headers.get_list("set-cookie") == [cookie]


async def test_a_failed_first_request_does_not_fork_the_workspace() -> None:
    # Development settings: the test client talks plain HTTP and would not return a Secure cookie.
    client, access = build(settings=settings_for_tests(environment="development"))

    await client.get("/browser/fails")  # the client keeps the cookie of the problem response
    second = await client.get("/browser")

    assert second.json()["workspace_id"] == "ws-1"
    assert "set-cookie" not in second.headers
    assert [name for name, _ in access.calls] == ["open_workspace", "open_workspace"]


async def test_cookie_is_not_secure_in_development_only() -> None:
    development, _ = build(settings=settings_for_tests(environment="development"))
    test, _ = build(settings=settings_for_tests(environment="test"))

    assert "secure" not in (await development.get("/browser")).headers["set-cookie"].lower()
    assert "secure" in (await test.get("/browser")).headers["set-cookie"].lower()


async def test_max_age_follows_the_workspace_lifetime() -> None:
    client, _ = build(settings=settings_for_tests(access={"workspace_ttl_days": 3}))

    response = await client.get("/browser")

    assert f"Max-Age={3 * 24 * 60 * 60}" in response.headers["set-cookie"]


async def test_a_known_cookie_returns_the_same_workspace_and_sets_nothing() -> None:
    client, access = build()
    await client.get("/browser")

    response = await client.get("/browser", headers={"Cookie": "vr_ws=cookie-1"})

    assert response.json()["workspace_id"] == "ws-1"
    assert "set-cookie" not in response.headers
    assert access.calls[-1] == ("open_workspace", ("cookie-1",))


async def test_a_cookie_the_facade_did_not_issue_yields_a_new_workspace_and_cookie() -> None:
    client, _ = build()
    await client.get("/browser")
    client.cookies.clear()

    response = await client.get("/browser", headers={"Cookie": "vr_ws=forged"})

    assert response.json()["workspace_id"] == "ws-2"
    assert "vr_ws=cookie-2" in response.headers["set-cookie"]


async def test_browser_principal_ignores_an_authorization_header() -> None:
    client, access = build()
    secret, _ = await issue_key(client, access)
    client.cookies.clear()

    response = await client.get("/browser", headers={"Authorization": f"Bearer {secret}"})

    assert response.json()["kind"] == "browser"
    assert response.json()["workspace_id"] == "ws-2"
    assert "authenticate_api_key" not in [name for name, _ in access.calls]


# api_key_principal


async def test_a_valid_key_authenticates_then_passes_the_rate_check() -> None:
    client, access = build()
    secret, workspace_id = await issue_key(client, access)
    access.calls.clear()

    response = await client.get("/key", headers={"Authorization": f"Bearer {secret}"})

    assert response.json() == {"workspace_id": workspace_id, "kind": "api_key", "key_id": "key-1"}
    assert [name for name, _ in access.calls] == ["authenticate_api_key", "check_rate"]
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "fake-api-key-1"},
        {"Authorization": "Bearer unknown-key"},
    ],
)
async def test_a_missing_malformed_or_unknown_key_is_forbidden(headers: dict[str, str]) -> None:
    client, access = build()
    await issue_key(client, access)

    response = await client.get("/key", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_a_rate_limited_key_is_answered_429() -> None:
    client, access = build()
    secret, _ = await issue_key(client, access)
    access.rate_limited.add("key-1")

    response = await client.get("/key", headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"


# any_principal


async def test_any_principal_uses_the_cookie_without_an_authorization_header() -> None:
    client, _ = build()

    response = await client.get("/any")

    assert response.json()["kind"] == "browser"
    assert "vr_ws=cookie-1" in response.headers["set-cookie"]


async def test_any_principal_uses_the_bearer_when_present() -> None:
    client, access = build()
    secret, workspace_id = await issue_key(client, access)

    response = await client.get("/any", headers={"Authorization": f"Bearer {secret}"})

    assert response.json() == {"workspace_id": workspace_id, "kind": "api_key", "key_id": "key-1"}


@pytest.mark.parametrize("authorization", ["Bearer unknown-key", "Basic dXNlcjpwYXNz", "Bearer"])
async def test_any_principal_with_a_bad_bearer_never_falls_back_to_the_cookie(
    authorization: str,
) -> None:
    client, access = build()
    await client.get("/browser")
    access.calls.clear()

    response = await client.get(
        "/any", headers={"Authorization": authorization, "Cookie": "vr_ws=cookie-1"}
    )

    assert response.status_code == 403
    assert "open_workspace" not in [name for name, _ in access.calls]
    assert "set-cookie" not in response.headers


# visitor_ref


async def test_visitor_ref_passes_the_socket_peer_and_the_allowance_code() -> None:
    client, access = build()

    response = await client.get(
        "/visitor", headers={"Veranico-Allowance-Code": "test-allowance-code"}
    )

    assert access.calls == [("visitor", (CLIENT_ADDRESS, "test-allowance-code"))]
    assert response.json()["boosted"] is True
    assert CLIENT_ADDRESS not in response.text


async def test_visitor_ref_without_the_header_passes_no_code() -> None:
    client, access = build()

    response = await client.get("/visitor")

    assert access.calls == [("visitor", (CLIENT_ADDRESS, None))]
    assert response.json()["boosted"] is False


@pytest.mark.parametrize(
    ("forwarded", "expected"),
    [
        ("198.51.100.9", "198.51.100.9"),
        ("10.0.0.1, 198.51.100.9", "198.51.100.9"),
        ("spoofed, 1.2.3.4,198.51.100.9 ", "198.51.100.9"),
        ("2001:db8::1, 2001:db8::2", "2001:db8::2"),
        ("", CLIENT_ADDRESS),
        ("198.51.100.9, ", CLIENT_ADDRESS),
    ],
)
async def test_visitor_ref_takes_the_entry_the_platform_appended(
    forwarded: str, expected: str
) -> None:
    client, access = build()

    await client.get("/visitor", headers={"X-Forwarded-For": forwarded})

    assert access.calls == [("visitor", (expected, None))]


async def test_visitor_ref_leaves_no_address_or_code_in_a_log_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = build()

    with caplog.at_level(logging.DEBUG):
        await client.get(
            "/visitor",
            headers={"X-Forwarded-For": "198.51.100.9", "Veranico-Allowance-Code": "the-code"},
        )

    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "198.51.100.9" not in logged
    assert CLIENT_ADDRESS not in logged
    assert "the-code" not in logged


# require_service_identity


def _token_settings() -> Settings:
    return settings_for_tests(
        delivery={"internal_auth": "token", "internal_token": "internal-token"}
    )


def _oidc_settings() -> Settings:
    return settings_for_tests(
        delivery={"internal_auth": "oidc", "oidc_audience": AUDIENCE, "oidc_invoker_email": INVOKER}
    )


async def test_disabled_mode_accepts_any_caller() -> None:
    client, _ = build(settings=settings_for_tests(delivery={"internal_auth": "disabled"}))

    assert (await client.post("/internal")).status_code == 200


async def test_token_mode_accepts_the_configured_token() -> None:
    client, _ = build(settings=_token_settings())

    response = await client.post("/internal", headers={"Authorization": "Bearer internal-token"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "Bearer internal-token-and-more"},
        {"Authorization": "Bearer internal"},
        {"Authorization": "internal-token"},
        {"Authorization": "Basic internal-token"},
    ],
)
async def test_token_mode_rejects_a_missing_or_wrong_token(headers: dict[str, str]) -> None:
    client, _ = build(settings=_token_settings())

    response = await client.post("/internal", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_oidc_mode_accepts_the_invoker_with_the_configured_audience() -> None:
    client, _ = build(settings=_oidc_settings())

    response = await client.post(
        "/internal", headers={"Authorization": f"Bearer {AUDIENCE}|{INVOKER}|true"}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        f"Bearer https://other.example|{INVOKER}|true",
        f"Bearer {AUDIENCE}|someone-else@example.iam.gserviceaccount.com|true",
        f"Bearer {AUDIENCE}|{INVOKER}|false",
        "Bearer not-a-token",
        f"Basic {AUDIENCE}|{INVOKER}|true",
    ],
    ids=["missing", "wrong-audience", "wrong-account", "unverified-email", "garbage", "not-bearer"],
)
async def test_oidc_mode_rejects_every_other_caller(authorization: str | None) -> None:
    client, _ = build(settings=_oidc_settings())
    headers = {} if authorization is None else {"Authorization": authorization}

    response = await client.post("/internal", headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_oidc_mode_does_not_accept_the_development_token() -> None:
    settings = settings_for_tests(
        delivery={
            "internal_auth": "oidc",
            "oidc_audience": AUDIENCE,
            "oidc_invoker_email": INVOKER,
            "internal_token": "internal-token",
        }
    )
    client, _ = build(settings=settings)

    response = await client.post("/internal", headers={"Authorization": "Bearer internal-token"})

    assert response.status_code == 403
