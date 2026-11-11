"""The registry as a whole: the seven tools, error mapping, summaries."""

import json

import pytest

from tests.fakes import builders
from tests.unit.assistant.tools.kit import (
    BROWSER,
    INDEX_ARGUMENTS,
    LIMIT_CENTS,
    SORRISO,
    Kit,
    build_kit,
)
from veranico.modules.assistant.contracts import ToolError
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import WeatherSourceUnavailableError
from veranico.shared.kernel.ids import DatasetId

pytestmark = pytest.mark.req("R-9.4-8")

TOOLS = [
    "resolve_location",
    "get_weather_history",
    "backtest_index",
    "price_cover",
    "find_extreme_seasons",
    "draft_term_sheet",
    "request_submission",
]


@pytest.mark.req("R-9.2-4")
@pytest.mark.req("R-9.3-3")
def test_registry_has_exactly_the_seven_tools() -> None:
    definitions = build_kit().registry.definitions()

    # The SPEC 9.4 table, in its order: no tool decides an approval, none searches documents.
    assert [definition.name for definition in definitions] == TOOLS
    assert not [d.name for d in definitions if "approv" in d.name or "decide" in d.name]


def test_every_definition_is_a_closed_json_schema_with_a_description() -> None:
    for definition in build_kit().registry.definitions():
        schema = definition.input_schema
        assert schema["type"] == "object", definition.name
        assert schema["additionalProperties"] is False, definition.name
        assert len(definition.description) > 80, definition.name
        json.dumps(schema)  # serialisable as it is


def test_definitions_are_identical_between_calls() -> None:
    registry = build_kit().registry

    assert registry.definitions() == registry.definitions()
    assert registry.definitions() == build_kit().registry.definitions()


@pytest.mark.req("R-9.4-9")
async def test_validation_error_becomes_invalid_arguments_with_field_and_reason() -> None:
    kit = build_kit()
    arguments = {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "index_type": "frost_below",
        "trigger": "plenty",
        "limit_cents": LIMIT_CENTS,
    }

    outcome = await kit.registry.execute(BROWSER, "backtest_index", arguments)

    assert not outcome.ok
    assert outcome.result is None
    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.retryable is False
    fields = {part.split(": ")[0] for part in outcome.error.message.split("; ")}
    assert fields == {"index_type", "trigger"}
    assert "rainfall_below" in outcome.error.message  # the reason names the allowed values
    assert outcome.summary == Coded(code="tool.error", params={"error_code": "invalid_arguments"})
    assert kit.pricing.calls == []


@pytest.mark.req("R-9.4-9")
async def test_a_placeholder_limit_is_refused_before_any_module_is_called() -> None:
    # The first evaluation run saw `limit_cents: 0` sent when the user had given no limit.
    kit = build_kit()
    arguments = {"dataset_id": kit.dataset.dataset_id, **INDEX_ARGUMENTS, "limit_cents": 0}

    outcome = await kit.registry.execute(BROWSER, "backtest_index", arguments)

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.message.startswith("limit_cents: ")
    assert kit.pricing.calls == []
    schemas = {spec.name: spec.input_schema for spec in kit.registry.definitions()}
    for tool in ("backtest_index", "price_cover"):
        assert schemas[tool]["properties"]["limit_cents"]["exclusiveMinimum"] == 0


@pytest.mark.req("R-9.4-9")
async def test_unknown_field_is_invalid_arguments() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(
        BROWSER, "get_weather_history", {"lat": SORRISO.lat, "lon": SORRISO.lon, "years": 30}
    )

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.message.startswith("years: ")


@pytest.mark.req("R-9.4-9")
async def test_unknown_tool_name_becomes_invalid_arguments() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "approve_submission", {"approval_id": "S-1"})

    assert outcome.error == ToolError(
        error_code="invalid_arguments", message="unknown tool: approve_submission", retryable=False
    )
    assert outcome.summary == Coded(code="tool.error", params={"error_code": "invalid_arguments"})
    assert kit.quoting.calls == []


async def _location_not_found(kit: Kit) -> tuple[str, dict[str, object]]:
    return "resolve_location", {"query": "Atlantis"}


async def _outside_coverage(kit: Kit) -> tuple[str, dict[str, object]]:
    return "get_weather_history", {"lat": 48.85, "lon": 2.35}


async def _weather_source_unavailable(kit: Kit) -> tuple[str, dict[str, object]]:
    kit.climate.fail_with(WeatherSourceUnavailableError())
    return "get_weather_history", {"lat": SORRISO.lat, "lon": SORRISO.lon}


async def _invalid_cover(kit: Kit) -> tuple[str, dict[str, object]]:
    # For rainfall_below the exit must be below the trigger.
    return "backtest_index", {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "exit": 500.0,
        "limit_cents": LIMIT_CENTS,
    }


async def _insufficient_history(kit: Kit) -> tuple[str, dict[str, object]]:
    short = DatasetId("point:86a8100c7ffffff")
    kit.pricing.add_dataset(short, seasons=10)
    return "backtest_index", {"dataset_id": short, **INDEX_ARGUMENTS, "limit_cents": LIMIT_CENTS}


async def _invalid_state(kit: Kit) -> tuple[str, dict[str, object]]:
    quote = kit.quoting.seed_quote(builders.quote_view(status="rejected"))
    return "request_submission", {"quote_id": quote.quote_id, "carrier_id": "carrier-1"}


async def _unknown_carrier(kit: Kit) -> tuple[str, dict[str, object]]:
    return "request_submission", {"quote_id": await kit.priced_quote_id(), "carrier_id": "nobody"}


async def _not_found(kit: Kit) -> tuple[str, dict[str, object]]:
    return "draft_term_sheet", {"quote_id": "Q-ZZZZZZ"}


@pytest.mark.req("R-9.1-3")
@pytest.mark.parametrize(
    ("code", "retryable", "arrange"),
    [
        ("location_not_found", False, _location_not_found),
        ("outside_coverage", False, _outside_coverage),
        ("weather_source_unavailable", True, _weather_source_unavailable),
        ("invalid_cover", False, _invalid_cover),
        ("insufficient_history", False, _insufficient_history),
        ("invalid_state", False, _invalid_state),
        ("unknown_carrier", False, _unknown_carrier),
        ("not_found", False, _not_found),
    ],
)
async def test_domain_error_becomes_tool_error_with_code_and_retryable(
    code: str, retryable: bool, arrange: object
) -> None:
    kit = build_kit()
    assert callable(arrange)
    tool, arguments = await arrange(kit)

    outcome = await kit.registry.execute(BROWSER, tool, arguments)

    assert not outcome.ok
    assert outcome.result is None
    assert outcome.approval is None
    assert outcome.error is not None
    assert outcome.error.error_code == code
    assert outcome.error.retryable is retryable
    assert outcome.error.message
    assert outcome.summary == Coded(code="tool.error", params={"error_code": code})
    # The payload the model sees is exactly `{error_code, message, retryable}`.
    assert set(outcome.error.model_dump()) == {"error_code", "message", "retryable"}


@pytest.mark.req("R-9.1-3")
async def test_unexpected_exception_does_not_escape_as_a_tool_result() -> None:
    kit = build_kit()

    # The climate fake raises `LookupError` for a point no test registered: a defect, not a
    # domain error. It is not dressed up as a tool result; it propagates and ends the turn.
    with pytest.raises(LookupError):
        await kit.registry.execute(BROWSER, "get_weather_history", {"lat": -20.0, "lon": -50.0})


async def test_summary_code_and_params_per_tool() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()
    dataset_id = kit.dataset.dataset_id
    calls: list[tuple[str, dict[str, object]]] = [
        ("resolve_location", {"query": "Sorriso"}),
        ("get_weather_history", {"lat": SORRISO.lat, "lon": SORRISO.lon}),
        (
            "backtest_index",
            {"dataset_id": dataset_id, **INDEX_ARGUMENTS, "limit_cents": LIMIT_CENTS},
        ),
        ("price_cover", kit.price_arguments()),
        (
            "find_extreme_seasons",
            {
                "dataset_id": dataset_id,
                "index_type": "rainfall_below",
                "window_start": "11-15",
                "window_end": "02-15",
            },
        ),
        ("draft_term_sheet", {"quote_id": quote_id}),
        ("request_submission", {"quote_id": quote_id, "carrier_id": "carrier-1"}),
    ]

    summaries = {}
    for tool, arguments in calls:
        outcome = await kit.registry.execute(BROWSER, tool, arguments)
        assert outcome.ok, (tool, outcome.error)
        summaries[tool] = outcome.summary

    # The codes and the parameter names the interface catalogue has (`tool.<name>`).
    assert {tool: (s.code, sorted(s.params)) for tool, s in summaries.items()} == {
        "resolve_location": ("tool.resolve_location", ["label", "lat", "lon"]),
        "get_weather_history": (
            "tool.get_weather_history",
            ["dataset_id", "first_year", "last_year", "source"],
        ),
        "backtest_index": ("tool.backtest_index", ["seasons_used", "trigger_frequency_rate"]),
        "price_cover": ("tool.price_cover", ["premium_cents", "quote_id"]),
        "find_extreme_seasons": ("tool.find_extreme_seasons", ["count"]),
        "draft_term_sheet": ("tool.draft_term_sheet", []),
        "request_submission": ("tool.request_submission", ["carrier_id", "submission_id"]),
    }
    # By the contracts conventions a money parameter ends in `_cents` and a rate in `_rate`.
    for summary in summaries.values():
        for name, value in summary.params.items():
            if name.endswith("_cents"):
                assert type(value) is int, name
            if name.endswith("_rate"):
                assert isinstance(value, str), name
                assert len(value.split(".")[1]) == 6, name
    assert summaries["find_extreme_seasons"].params == {"count": 5}  # the default top_n


async def test_results_are_plain_json() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "price_cover", kit.price_arguments())

    assert outcome.result is not None
    assert json.loads(json.dumps(outcome.result)) == outcome.result
