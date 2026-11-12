"""The tool registry: the seven tools of SPEC 9.4 and nothing else.

`execute` validates the arguments with the tool's input model, calls the facade and returns a
`ToolOutcome`. A validation error, an unknown tool name and every `DomainError` become a
`ToolError` (`{error_code, message, retryable}`), which the loop hands to the model as the
tool result. Any other exception (a defect, a storage failure) is logged with its stack and
becomes the non-retryable `internal_error`, whose message says nothing of the exception: the
model never sees an exception, its text or a path (SPEC 9.1). There is no tool that decides
an approval and no retrieval over documents.

Tool summaries (`ToolFinished.summary`). This table is the single place the interface reads
the codes and their parameters from. A parameter ending in `_cents` is integer BRL centavos
and one ending in `_rate` is a `Rate` string; the interface formats both.

| Code | Parameters |
|---|---|
| `tool.resolve_location` | `label` (str), `lat` (float), `lon` (float) |
| `tool.resolve_location.candidates` | `count` (int) |
| `tool.get_weather_history` | `dataset_id` (str), `first_year`, `last_year` (int), `source` (str) |
| `tool.backtest_index` | `seasons_used` (int), `trigger_frequency_rate` (Rate) |
| `tool.price_cover` | `quote_id` (str), `premium_cents` (int) |
| `tool.find_extreme_seasons` | `count` (int) |
| `tool.draft_term_sheet` | none |
| `tool.request_submission` | `submission_id` (str), `carrier_id` (str) |
| `tool.error` | `error_code` (str) |

Tool results (`ToolFinished.result`, the output model serialised with `mode="json"`):

| Tool | Result |
|---|---|
| `resolve_location` | `Location`, or `{"candidates": [Location, ...]}` |
| `get_weather_history` | `DatasetRef` |
| `backtest_index` | `BacktestResult` |
| `price_cover` | `{"quote_id": ..., "priced": PricedCover}` |
| `find_extreme_seasons` | `{"seasons": [ExtremeSeason, ...]}` |
| `draft_term_sheet` | `{"documents": [DocumentRef, ...]}` |
| `request_submission` | `Submission` |
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from veranico.modules.assistant.application.ports import ToolSpec
from veranico.modules.assistant.application.tools.backtest_index import backtest_index_tool
from veranico.modules.assistant.application.tools.draft_term_sheet import draft_term_sheet_tool
from veranico.modules.assistant.application.tools.find_extreme_seasons import (
    find_extreme_seasons_tool,
)
from veranico.modules.assistant.application.tools.get_weather_history import (
    get_weather_history_tool,
)
from veranico.modules.assistant.application.tools.models import Tool, ToolOutcome
from veranico.modules.assistant.application.tools.price_cover import price_cover_tool
from veranico.modules.assistant.application.tools.request_submission import request_submission_tool
from veranico.modules.assistant.application.tools.resolve_location import resolve_location_tool
from veranico.modules.assistant.contracts import ToolError
from veranico.modules.carriers.contracts import CarriersFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import DomainError, InternalError
from veranico.shared.kernel.principal import Principal

_logger = logging.getLogger(__name__)

# What the model reads for an unexpected failure. It may tell the user; it holds no internals.
UNEXPECTED_FAILURE = "the tool failed unexpectedly; it is not worth retrying in this turn"


class ToolRegistry:
    def __init__(
        self,
        *,
        climate: ClimateFacade,
        pricing: PricingFacade,
        quoting: QuotingFacade,
        documents: DocumentsFacade,
        carriers: CarriersFacade,
    ) -> None:
        # `Any`: each tool is generic in its own input model, and `execute` pairs a tool's
        # handler only with an instance its own `input_model` validated.
        tools: Sequence[Tool[Any]] = (
            resolve_location_tool(climate),
            get_weather_history_tool(climate),
            backtest_index_tool(pricing),
            price_cover_tool(quoting),
            find_extreme_seasons_tool(pricing),
            draft_term_sheet_tool(documents),
            request_submission_tool(quoting, carriers.catalog().all()),
        )
        self._tools: Mapping[str, Tool[Any]] = {tool.name: tool for tool in tools}

    def definitions(self) -> Sequence[ToolSpec]:
        """The tool definitions for the model, in the order of the SPEC 9.4 table."""
        return tuple(
            ToolSpec(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema or tool.input_model.model_json_schema(),
            )
            for tool in self._tools.values()
        )

    async def execute(
        self, principal: Principal, name: str, arguments: Mapping[str, object]
    ) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return _failed("invalid_arguments", f"unknown tool: {name}", retryable=False)
        try:
            validated = tool.input_model.model_validate(dict(arguments))
        except ValidationError as error:
            return _failed("invalid_arguments", _reasons(error), retryable=False)
        try:
            success = await tool.handler(principal, validated)
        except DomainError as error:
            return _failed(error.code, str(error), retryable=error.retryable)
        except Exception:
            # The name only: arguments are user data and stay out of the log.
            _logger.exception("tool %s failed unexpectedly", name)
            return _failed(InternalError.code, UNEXPECTED_FAILURE, retryable=False)
        return ToolOutcome(
            summary=success.summary,
            result=success.output.model_dump(mode="json"),
            approval=success.approval,
        )


def _failed(code: str, message: str, *, retryable: bool) -> ToolOutcome:
    return ToolOutcome(
        summary=Coded(code="tool.error", params={"error_code": code}),
        error=ToolError(error_code=code, message=message, retryable=retryable),
    )


def _reasons(error: ValidationError) -> str:
    """`field: reason` for every invalid field, so the model can correct its arguments."""
    parts = []
    for item in error.errors(include_url=False, include_input=False, include_context=False):
        field = ".".join(str(part) for part in item["loc"]) or "arguments"
        parts.append(f"{field}: {item['msg']}")
    return "; ".join(parts)
