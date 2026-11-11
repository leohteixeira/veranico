import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from veranico.shared.infrastructure import problems, telemetry
from veranico.shared.infrastructure.problems import install_problem_handlers, problem_response
from veranico.shared.kernel import errors


def _body(response: object) -> dict[str, object]:
    return json.loads(response.body)  # type: ignore[attr-defined, no-any-return]  # JSONResponse.body


def test_domain_error_becomes_the_problem_document() -> None:
    response = problem_response(
        errors.InvalidCoverError("exit must be below the trigger"), "abc123"
    )

    assert response.status_code == 422
    assert response.media_type == "application/problem+json"
    assert _body(response) == {
        "type": "https://veranico.dev/problems/invalid_cover",
        "title": "Invalid cover",
        "status": 422,
        "code": "invalid_cover",
        "detail": "exit must be below the trigger",
        "trace_id": "abc123",
    }


def test_detail_is_left_out_when_the_error_has_none_and_trace_id_is_always_a_string() -> None:
    body = _body(problem_response(errors.NotFoundError(), None))

    assert body == {
        "type": "https://veranico.dev/problems/not_found",
        "title": "Not found",
        "status": 404,
        "code": "not_found",
        "trace_id": "",
    }


@pytest.mark.parametrize("cls", [errors.AllowanceExhaustedError, errors.SpendCeilingReachedError])
def test_the_two_replay_codes_carry_replay_available(cls: type[errors.DomainError]) -> None:
    body = _body(problem_response(cls(), "t"))

    assert body["replay_available"] is True
    assert body["status"] == 429


def test_no_other_code_carries_replay_available() -> None:
    others = [
        cls for cls in errors.DomainError.__subclasses__() if cls.code not in problems.REPLAY_CODES
    ]

    assert len(others) == 20
    assert all("replay_available" not in _body(problem_response(cls(), "t")) for cls in others)


class _Body(BaseModel):
    limit_cents: int


def _app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise errors.DatasetNotFoundError("no such dataset")

    @app.post("/quotes")
    async def create(body: _Body) -> _Body:
        return body

    return app


async def _call(method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)  # type: ignore[arg-type]  # test passthrough


async def test_handler_maps_a_raised_domain_error() -> None:
    response = await _call("GET", "/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "dataset_not_found"
    assert response.json()["detail"] == "no such dataset"


async def test_request_validation_error_becomes_invalid_arguments() -> None:
    response = await _call("POST", "/quotes", json={"limit_cents": "a private value"})

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "invalid_arguments"
    assert body["type"] == "https://veranico.dev/problems/invalid_arguments"
    assert body["detail"].startswith("body.limit_cents: ")
    assert "a private value" not in response.text


async def test_trace_id_comes_from_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "current_trace_id", lambda: "0af7651916cd43dd8448eb211c80319c")

    response = await _call("GET", "/missing")

    assert response.json()["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
