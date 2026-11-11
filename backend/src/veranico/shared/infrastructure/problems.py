"""RFC 9457 problem documents: the one place that turns errors into HTTP answers."""

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from veranico.shared.infrastructure import telemetry
from veranico.shared.kernel.errors import (
    DomainError,
    InvalidArgumentsError,
    NotImplementedYetError,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://veranico.dev/problems/"
# The interface offers the recorded replay when it sees one of these.
REPLAY_CODES = frozenset({"allowance_exhausted", "spend_ceiling_reached"})


# Every route may answer with a problem document. Passed to `FastAPI(responses=...)`, it
# also keeps FastAPI's own validation error body, which is never sent, out of OpenAPI.
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {
        "description": "Problem document (RFC 9457); the stable `code` names the error.",
        "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
    }
}


class Problem(BaseModel):
    """The problem document. The interface translates `code`, never the English text."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    trace_id: str
    replay_available: bool | None = None


def problem_response(error: DomainError, trace_id: str | None) -> JSONResponse:
    problem = Problem(
        type=f"{PROBLEM_TYPE_BASE}{error.code}",
        title=error.code.replace("_", " ").capitalize(),
        status=error.status,
        code=error.code,
        detail=error.detail,
        trace_id=trace_id or "",
        replay_available=True if error.code in REPLAY_CODES else None,
    )
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=error.status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def validation_detail(errors: Sequence[Any]) -> str:
    """Name each rejected field and the reason. The rejected input is never echoed."""
    parts = []
    for error in errors:
        location = ".".join(str(item) for item in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


async def _domain_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, DomainError)
    return problem_response(error, telemetry.current_trace_id())


async def _validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    invalid = InvalidArgumentsError(validation_detail(error.errors()))
    return problem_response(invalid, telemetry.current_trace_id())


async def _not_implemented(request: Request, error: Exception) -> JSONResponse:
    """A facade or route of a module that has not landed yet: `501`, not a server error."""
    return problem_response(NotImplementedYetError(), telemetry.current_trace_id())


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(NotImplementedError, _not_implemented)
