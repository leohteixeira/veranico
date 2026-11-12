"""Two consumers, one service (SPEC 3.2): the agent's tools and the public API.

What is proven here, structurally and without a model:

* every tool does its work through methods of the module contracts (`contracts.py` facades),
  and each of those facades is one a public router is built on, so the agent has no path of
  its own into a module;
* the capability each tool gives has a public operation, and each public operation has a tool
  or a stated reason why the agent does not have it. Both lists are complete: a new tool or a
  new public operation without an entry fails here.

The tables at the bottom are the statement of parity. They name its two known differences: a
place is looked up by name only in the conversation (the public API takes coordinates), and
a person, never the agent, decides an approval (SPEC 6).
"""

import inspect
import json
from pathlib import Path
from typing import Any, get_type_hints

import pytest

from tests.unit.assistant.tools.kit import BROWSER, INDEX_ARGUMENTS, LIMIT_CENTS, SORRISO, build_kit
from veranico.modules.access.http import router as access_router
from veranico.modules.assistant.application.tools.registry import ToolRegistry
from veranico.modules.assistant.http import router as assistant_router
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.climate.http import router as climate_router
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.http import router as documents_router
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.pricing.http import router as pricing_router
from veranico.modules.quoting.contracts import QuotingFacade
from veranico.modules.quoting.http import router as quoting_router

pytestmark = pytest.mark.req("R-3.2-1")

OPENAPI = Path(__file__).parents[3] / "openapi.json"
PUBLIC_ROUTERS = (
    access_router,
    assistant_router,
    climate_router,
    documents_router,
    pricing_router,
    quoting_router,
)


def facades_of(function: Any) -> set[type]:
    """The contract facades a function takes, by its annotations."""
    hints = get_type_hints(function)
    return {
        hint
        for name, hint in hints.items()
        if name != "return" and inspect.isclass(hint) and hint.__name__.endswith("Facade")
    }


async def facade_calls_per_tool() -> dict[str, set[tuple[type, str]]]:
    """Runs every tool once on the fakes: the facade methods each one called."""
    kit = build_kit()
    fakes: dict[type, Any] = {
        ClimateFacade: kit.climate,
        PricingFacade: kit.pricing,
        QuotingFacade: kit.quoting,
        DocumentsFacade: kit.documents,
    }
    index = {**INDEX_ARGUMENTS, "limit_cents": LIMIT_CENTS}
    quote_id = await kit.priced_quote_id()
    arguments: dict[str, dict[str, object]] = {
        "resolve_location": {"query": "Sorriso"},
        "get_weather_history": {"lat": SORRISO.lat, "lon": SORRISO.lon},
        "backtest_index": {"dataset_id": kit.dataset.dataset_id, **index},
        "price_cover": kit.price_arguments(),
        "find_extreme_seasons": {
            "dataset_id": kit.dataset.dataset_id,
            "index_type": INDEX_ARGUMENTS["index_type"],
            "window_start": INDEX_ARGUMENTS["window_start"],
            "window_end": INDEX_ARGUMENTS["window_end"],
        },
        "draft_term_sheet": {"quote_id": quote_id},
        "request_submission": {"quote_id": quote_id, "carrier_id": "carrier-1"},
    }
    assert set(arguments) == {tool.name for tool in kit.registry.definitions()}

    called: dict[str, set[tuple[type, str]]] = {}
    for tool, given in arguments.items():
        for fake in (*fakes.values(), kit.carriers):
            fake.calls.clear()
        outcome = await kit.registry.execute(BROWSER, tool, given)
        assert outcome.ok, (tool, outcome.error)
        assert kit.carriers.calls == [], tool  # the directory is read once, to list the carriers
        called[tool] = {
            (facade, method) for facade, fake in fakes.items() for method, _ in fake.calls
        }
    return called


async def test_every_tool_works_through_contract_facades_the_public_api_is_built_on() -> None:
    public = set().union(*(facades_of(module.build_router) for module in PUBLIC_ROUTERS))

    called = await facade_calls_per_tool()

    for tool, calls in called.items():
        assert calls, f"{tool} called no module facade"
        for facade, method in calls:
            assert callable(getattr(facade, method, None)), f"{tool}: {method} is not a contract"
            assert facade in public, f"{tool}: no public router is built on {facade.__name__}"
    # The registry is given facades and nothing else: no store, no client, no settings.
    hints = get_type_hints(ToolRegistry.__init__)
    assert {name for name in hints if name != "return"} == {
        "climate",
        "pricing",
        "quoting",
        "documents",
        "carriers",
    }
    assert all(hints[name].__name__.endswith("Facade") for name in hints if name != "return")


async def test_tools_that_share_a_facade_method_with_a_route_are_the_ones_the_table_says() -> None:
    called = await facade_calls_per_tool()

    # Where the table names a method, the tool calls exactly that method, as the route does.
    for tool, (operation, shared) in TOOL_TO_PUBLIC.items():
        if shared is not None:
            assert shared in called[tool], (tool, operation)


def test_every_tool_has_a_public_operation_and_every_operation_a_tool_or_a_reason() -> None:
    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    operations = {
        operation["operationId"]
        for methods in document["paths"].values()
        for operation in methods.values()
    }
    tools = {definition.name for definition in build_kit().registry.definitions()}

    assert set(TOOL_TO_PUBLIC) == tools
    assert set(PUBLIC_TO_TOOL) == operations
    for tool, (operation, _) in TOOL_TO_PUBLIC.items():
        assert operation in operations or operation in AGENT_ONLY, tool
    for operation, counterpart in PUBLIC_TO_TOOL.items():
        if counterpart in tools:
            # The two tables agree: the tool's own entry points back at this operation.
            assert TOOL_TO_PUBLIC[counterpart][0] == operation, operation
        else:
            assert len(counterpart) > 20, f"{operation}: state why the agent does not have it"
    # The only capability the agent has and the public API lacks, and the reason.
    assert [tool for tool, (operation, _) in TOOL_TO_PUBLIC.items() if operation in AGENT_ONLY] == [
        "resolve_location"
    ]


AGENT_ONLY = {
    "name lookup": (
        "The public API takes coordinates; a place is looked up by name only in the "
        "conversation. `POST /quotes` resolves its coordinates through the same "
        "`ClimateFacade.resolve_location`."
    ),
}

# Tool -> (the public operation that gives the same capability, the facade method both call
# when they call the same one). Where the method is None the route reaches the capability
# through another method of the same facade.
TOOL_TO_PUBLIC: dict[str, tuple[str, tuple[type, str] | None]] = {
    "resolve_location": ("name lookup", None),
    "get_weather_history": ("get_season_series", (ClimateFacade, "ensure_history")),
    # `GET /weather/seasons` returns the per-season index and payout of every season.
    "backtest_index": ("get_season_series", None),
    "find_extreme_seasons": ("get_season_series", None),
    "price_cover": ("create_quote", (QuotingFacade, "create_quote")),
    # The download renders on demand; the tool renders both languages at once.
    "draft_term_sheet": ("get_term_sheet", None),
    "request_submission": ("request_submission", (QuotingFacade, "request_submission")),
}

# Public operation -> the tool with that capability, or why the agent does not have it.
PUBLIC_TO_TOOL: dict[str, str] = {
    "create_quote": "price_cover",
    "request_submission": "request_submission",
    "get_term_sheet": "draft_term_sheet",
    "get_season_series": "backtest_index",
    "decide_approval": "Only a person decides an approval, never the agent (SPEC 6).",
    "redeliver_approval": "Redelivery is part of the decision a person owns (SPEC 6).",
    "list_approvals": "The Approvals panel of the person who decides; the agent has no use for it.",
    "list_quotes": "A read view for the interface; the agent holds the quotes it created.",
    "get_quote": "A read view for the interface; the agent holds the quotes it created.",
    "get_evidence": "A file download; it carries no figure the agent would state.",
    "list_regions": "A map layer of the interface, not a step of structuring a cover.",
    "get_region_cells": "A map layer of the interface, not a step of structuring a cover.",
    "issue_api_key": "Access to the public API itself, not a capability over covers.",
    "get_allowance": "The visitor's allowance, shown by the interface.",
    "chat": "The agent itself: this route is how a visitor reaches it.",
    "get_conversation": "The stored conversation with the agent.",
    "get_replay": "The recorded conversation with the agent.",
    "sweep_outbox": "Internal: called by the scheduler, not a capability of a consumer.",
    "deliver_outbox_event": "Internal: called by the queue, not a capability of a consumer.",
    "healthz": "Operations, not a capability of a consumer.",
    "health": "Operations, not a capability of a consumer.",
    "readyz": "Operations, not a capability of a consumer.",
}
