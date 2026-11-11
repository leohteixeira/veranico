"""The HTTP contract: every route of SPEC section 11, with its final schemas.

`ROUTES` is the whole surface. The test fails on a missing route, an extra route or a
different schema name. `STILL_STUBBED` lists the routes that still answer `501`; a module
plan removes its routes from that set when it lands, and the schema assertions stay.
"""

import dataclasses
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.fakes.access import FakeAccessFacade
from tests.fakes.settings import settings_for_tests
from veranico.bootstrap import build_container
from veranico.main import create_app

EMULATOR = "127.0.0.1:8580"  # never contacted: the Firestore client connects on first use
V1 = "/api/v1"
SSE = "text/event-stream"

# (method, path, operation id, security schemes, request schema, response schema or media type)
Route = tuple[str, str, str, frozenset[str], str | None, str]

COOKIE = frozenset({"WorkspaceCookie"})
KEY = frozenset({"ApiKey"})
KEY_OR_COOKIE = COOKIE | KEY
SERVICE = frozenset({"ServiceIdentity"})
NONE: frozenset[str] = frozenset()

API_ROUTES: list[Route] = [
    ("POST", f"{V1}/quotes", "create_quote", KEY, "CreateQuote", "QuoteView"),
    ("GET", f"{V1}/quotes", "list_quotes", COOKIE, None, "list[QuoteSummary]"),
    ("GET", f"{V1}/quotes/{{id}}", "get_quote", KEY_OR_COOKIE, None, "QuoteView"),
    (
        "POST",
        f"{V1}/quotes/{{id}}/submissions",
        "request_submission",
        KEY_OR_COOKIE,
        "SubmissionRequest",
        "Submission",
    ),
    ("GET", f"{V1}/approvals", "list_approvals", COOKIE, None, "list[ApprovalView]"),
    (
        "POST",
        f"{V1}/approvals/{{id}}/decision",
        "decide_approval",
        COOKIE,
        "Decision",
        "ApprovalView",
    ),
    (
        "POST",
        f"{V1}/approvals/{{id}}/redeliver",
        "redeliver_approval",
        COOKIE,
        None,
        "ApprovalView",
    ),
    ("POST", f"{V1}/internal/outbox/sweep", "sweep_outbox", SERVICE, None, "SweepResult"),
    (
        "GET",
        f"{V1}/quotes/{{id}}/term-sheet.pdf",
        "get_term_sheet",
        KEY_OR_COOKIE,
        None,
        "application/pdf",
    ),
    (
        "GET",
        f"{V1}/quotes/{{id}}/evidence.nc",
        "get_evidence",
        KEY_OR_COOKIE,
        None,
        "application/x-netcdf",
    ),
    ("POST", f"{V1}/chat", "chat", COOKIE, "ChatRequest", SSE),
    ("GET", f"{V1}/conversations/{{id}}", "get_conversation", COOKIE, None, "ConversationView"),
    ("GET", f"{V1}/replays/{{locale}}", "get_replay", COOKIE, None, SSE),
    ("POST", f"{V1}/workspace/api-keys", "issue_api_key", COOKIE, None, "ApiKeyIssued"),
    ("GET", f"{V1}/allowance", "get_allowance", COOKIE, None, "Allowance"),
    ("GET", f"{V1}/regions", "list_regions", NONE, None, "list[Region]"),
    ("GET", f"{V1}/regions/{{id}}/cells", "get_region_cells", NONE, None, "CellGrid"),
    ("GET", f"{V1}/weather/seasons", "get_season_series", NONE, None, "SeasonSeries"),
    (
        "POST",
        f"{V1}/internal/outbox/{{event_id}}/deliver",
        "deliver_outbox_event",
        SERVICE,
        None,
        "DeliveryOutcome",
    ),
]
CARRIER_ROUTES: list[Route] = [
    (
        "POST",
        "/carrier/v1/submissions",
        "receive_submission",
        frozenset({"WebhookSignature"}),
        "WebhookEnvelope",
        "Receipt",
    ),
]
HEALTH_ROUTES: list[Route] = [
    ("GET", "/healthz", "healthz", NONE, None, "Health"),
    ("GET", "/readyz", "readyz", NONE, None, "Readiness"),
]

# Routes that still answer 501. In M0 it holds every product route.
STILL_STUBBED: set[tuple[str, str]] = {
    ("POST", f"{V1}/chat"),
    ("GET", f"{V1}/conversations/{{id}}"),
    ("GET", f"{V1}/replays/{{locale}}"),
}

INDEX = {"index_type", "window_start", "window_end", "trigger", "exit"}
# (method, path) -> (required, optional) parameters outside the path, as "<in>:<name>"
PARAMETERS: dict[tuple[str, str], tuple[set[str], set[str]]] = {
    ("POST", f"{V1}/quotes"): ({"header:Idempotency-Key"}, set()),
    ("GET", f"{V1}/approvals"): (set(), {"query:status"}),
    ("GET", f"{V1}/quotes/{{id}}/term-sheet.pdf"): (set(), {"query:lang"}),
    ("POST", f"{V1}/chat"): (set(), {"header:Veranico-Allowance-Code"}),
    ("GET", f"{V1}/allowance"): (set(), {"header:Veranico-Allowance-Code"}),
    ("GET", f"{V1}/regions/{{id}}/cells"): (
        {"query:metric"} | {f"query:{name}" for name in INDEX},
        {"query:season"},
    ),
    ("GET", f"{V1}/weather/seasons"): (
        {"query:lat", "query:lon"} | {f"query:{name}" for name in INDEX},
        {"query:limit_cents"},
    ),
    ("POST", "/carrier/v1/submissions"): (set(), {"header:Veranico-Timestamp"}),
}

EVENT_MODELS = {
    "Started",
    "UserMessage",
    "TextDelta",
    "ToolStarted",
    "ToolFinished",
    "ApprovalRequired",
    "GroundingFlagged",
    "StreamError",
    "Done",
}

# A request that passes validation for each stubbed route, so the handler itself answers.
INDEX_QUERY = {
    "index_type": "rainfall_below",
    "window_start": "10-01",
    "window_end": "03-31",
    "trigger": "600",
    "exit": "300",
}
COVER = {
    "index": {
        "index_type": "rainfall_below",
        "window": {"start": "10-01", "end": "03-31"},
        "trigger": 600,
        "exit": 300,
    },
    "limit": {"amount_cents": 10_000_000},
}
PAYLOAD = {
    "quote_id": "Q-ABC123",
    "submission_id": "S-ABC123",
    "location": {
        "label": "Sorriso",
        "lat": -12.5,
        "lon": -55.7,
        "h3_cell": "87a8a0000ffffff",
        "admin_region": None,
    },
    "cover": COVER,
    "premium": {"amount_cents": 500_000},
    "rate_on_line": "0.050000",
}
REQUESTS: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", f"{V1}/quotes"): {
        "json": {"location": {"lat": -12.5, "lon": -55.7}, "cover": COVER},
        "headers": {"Idempotency-Key": "key-1"},
    },
    ("POST", f"{V1}/quotes/{{id}}/submissions"): {"json": {"carrier_id": "carrier-1"}},
    ("POST", f"{V1}/approvals/{{id}}/decision"): {"json": {"approve": True}},
    ("POST", f"{V1}/chat"): {"json": {"conversation_id": None, "message": "hi", "locale": "en"}},
    ("GET", f"{V1}/regions/{{id}}/cells"): {
        "params": {"metric": "trigger_frequency", **INDEX_QUERY}
    },
    ("GET", f"{V1}/weather/seasons"): {"params": {"lat": "-12.5", "lon": "-55.7", **INDEX_QUERY}},
    ("POST", "/carrier/v1/submissions"): {
        "json": {
            "event_id": "0190a8e0-0000-7000-8000-000000000000",
            "event_type": "quoting.submission_approved",
            "version": 1,
            "occurred_at": "2026-01-01T00:00:00Z",
            "data": PAYLOAD,
        }
    },
}
PATH_VALUES = {"{id}": "Q-ABC123", "{event_id}": "event-1", "{locale}": "en"}


def app_for(role: str) -> FastAPI:
    return create_app(settings_for_tests(role, firestore_emulator_host=EMULATOR))  # type: ignore[arg-type]  # literal chosen by the caller


@pytest.fixture(scope="module")
def api_document() -> dict[str, Any]:
    return app_for("api").openapi()


@pytest.fixture(scope="module")
def carrier_document() -> dict[str, Any]:
    return app_for("carrier").openapi()


def operations(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in document["paths"].items()
        for method, operation in item.items()
    }


def schema_name(schema: dict[str, Any]) -> str | None:
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"list[{schema_name(schema['items'])}]"
    return None


def request_schema(operation: dict[str, Any]) -> str | None:
    if "requestBody" not in operation:
        return None
    return schema_name(operation["requestBody"]["content"]["application/json"]["schema"])


def response_schema(operation: dict[str, Any]) -> str:
    """The schema name of a JSON success body, else the media type."""
    content = operation["responses"]["200"]["content"]
    assert len(content) == 1, content
    media_type, body = next(iter(content.items()))
    if media_type == "application/json":
        name = schema_name(body["schema"])
        assert name is not None, body
        return name
    return str(media_type)


def security(operation: dict[str, Any]) -> frozenset[str]:
    return frozenset(name for entry in operation.get("security", []) for name in entry)


def described(operation: dict[str, Any], method: str, path: str) -> Route:
    return (
        method,
        path,
        operation["operationId"],
        security(operation),
        request_schema(operation),
        response_schema(operation),
    )


def assert_surface(document: dict[str, Any], expected: list[Route]) -> None:
    found = operations(document)
    assert set(found) == {(method, path) for method, path, *_ in expected}
    actual = sorted(described(operation, *key) for key, operation in found.items())
    assert actual == sorted(expected)


@pytest.mark.req(
    "R-11-1",
    "R-11.1-1",
    "R-11.1-2",
    "R-11.1-3",
    "R-11.1-4",
    "R-11.1-5",
    "R-11.2-1",
    "R-11.2-2",
    "R-11.2-3",
    "R-11.2-4",
    "R-11.2-5",
    "R-11.2-6",
    "R-11.2-7",
    "R-11.2-8",
    "R-11.2-9",
    "R-11.2-10",
    "R-11.2-11",
    "R-11.2-12",
    "R-11.2-13",
    "R-11.2-14",
    "R-11.3-1",
    "R-11.3-2",
)
def test_api_role_serves_exactly_the_routes_of_the_contract(api_document: dict[str, Any]) -> None:
    assert_surface(api_document, API_ROUTES + HEALTH_ROUTES)


@pytest.mark.req("R-11.4-1", "R-11.4-2")
def test_carrier_role_serves_exactly_its_routes(carrier_document: dict[str, Any]) -> None:
    assert_surface(carrier_document, CARRIER_ROUTES + HEALTH_ROUTES)


def test_operation_ids_are_unique(
    api_document: dict[str, Any], carrier_document: dict[str, Any]
) -> None:
    for document in (api_document, carrier_document):
        ids = [operation["operationId"] for operation in operations(document).values()]
        assert len(ids) == len(set(ids))


@pytest.mark.req("R-11.1-1")
def test_parameters_outside_the_path_are_the_documented_ones(
    api_document: dict[str, Any], carrier_document: dict[str, Any]
) -> None:
    found = {**operations(api_document), **operations(carrier_document)}
    for key, operation in found.items():
        declared = [p for p in operation.get("parameters", []) if p["in"] != "path"]
        required = {f"{p['in']}:{p['name']}" for p in declared if p.get("required")}
        optional = {f"{p['in']}:{p['name']}" for p in declared if not p.get("required")}
        assert (required, optional) == PARAMETERS.get(key, (set(), set())), key


def test_path_parameters_match_the_path(
    api_document: dict[str, Any], carrier_document: dict[str, Any]
) -> None:
    found = {**operations(api_document), **operations(carrier_document)}
    for (_, path), operation in found.items():
        declared = {p["name"] for p in operation.get("parameters", []) if p["in"] == "path"}
        in_path = {part[1:-1] for part in path.split("/") if part.startswith("{")}
        assert declared == in_path, path


def test_security_schemes_are_the_named_ones(
    api_document: dict[str, Any], carrier_document: dict[str, Any]
) -> None:
    assert set(api_document["components"]["securitySchemes"]) == {
        "WorkspaceCookie",
        "ApiKey",
        "ServiceIdentity",
    }
    assert set(carrier_document["components"]["securitySchemes"]) == {"WebhookSignature"}
    signature = carrier_document["components"]["securitySchemes"]["WebhookSignature"]
    assert (signature["in"], signature["name"]) == ("header", "Veranico-Signature")


def test_stream_event_models_are_in_the_components(api_document: dict[str, Any]) -> None:
    schemas = api_document["components"]["schemas"]

    assert set(schemas) >= EVENT_MODELS
    assert set(schemas["Started"]["properties"]) == {"conversation_id", "message_id"}
    assert set(schemas["ToolFinished"]["properties"]) == {
        "call_id",
        "tool",
        "status",
        "duration_ms",
        "summary",
        "result",
        "error",
    }
    assert schemas["Done"]["properties"]["stop_reason"]["enum"] == [
        "end_turn",
        "tool_limit",
        "budget",
        "error",
    ]


@pytest.mark.req("R-11-2")
def test_problem_document_is_in_the_components_and_is_every_error_answer(
    api_document: dict[str, Any], carrier_document: dict[str, Any]
) -> None:
    for document in (api_document, carrier_document):
        schemas = document["components"]["schemas"]
        assert set(schemas["Problem"]["properties"]) == {
            "type",
            "title",
            "status",
            "code",
            "detail",
            "trace_id",
            "replay_available",
        }
        # FastAPI's own validation error body is never sent: the problem handler answers.
        assert "HTTPValidationError" not in schemas
        assert "ValidationError" not in schemas
        for key, operation in operations(document).items():
            default = operation["responses"]["default"]["content"]
            assert default == {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            }, key
            assert "422" not in operation["responses"], key


def test_no_schema_is_split_into_input_and_output_variants(api_document: dict[str, Any]) -> None:
    assert not [name for name in api_document["components"]["schemas"] if "-" in name]


def test_document_is_deterministic() -> None:
    first = app_for("api").openapi()
    second = app_for("api").openapi()

    assert first == second
    assert list(first["components"]["schemas"]) == sorted(first["components"]["schemas"])


def test_stubbed_set_names_only_routes_of_the_contract() -> None:
    known = {(method, path) for method, path, *_ in API_ROUTES + CARRIER_ROUTES}

    assert known >= STILL_STUBBED


@pytest.mark.parametrize(("method", "path"), sorted(STILL_STUBBED))
async def test_stubbed_route_answers_501_with_a_problem_document(method: str, path: str) -> None:
    """The handler itself answers: authentication passes, backed by the fake `access`."""
    role = "carrier" if path.startswith("/carrier") else "api"
    container = build_container(settings_for_tests(role, firestore_emulator_host=EMULATOR))  # type: ignore[arg-type]  # literal chosen above
    request = dict(REQUESTS.get((method, path), {}))
    if container.access is not None:
        access = FakeAccessFacade()
        container = dataclasses.replace(
            container, access=dataclasses.replace(container.access, facade=access)
        )
        if (method, path) == ("POST", f"{V1}/quotes"):
            principal, _ = await access.open_workspace(None)
            key = await access.issue_api_key(principal)
            request["headers"] = {**request["headers"], "Authorization": f"Bearer {key.secret}"}
    app = create_app(container=container)
    url = path
    for placeholder, value in PATH_VALUES.items():
        url = url.replace(placeholder, value)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.request(method, url, **request)

    assert response.status_code == 501, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_implemented"
    assert body["status"] == 501
    assert body["type"] == "https://veranico.dev/problems/not_implemented"


async def test_cookie_route_opens_a_workspace_and_answers_from_the_real_modules() -> None:
    """With `access` and `quoting` landed, a first visit gets a workspace cookie and no quotes."""
    transport = httpx.ASGITransport(app=app_for("api"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get(f"{V1}/quotes")

    assert response.status_code == 200
    assert response.json() == []
    assert "vr_ws" in response.cookies
