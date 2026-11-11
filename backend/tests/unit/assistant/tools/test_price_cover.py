import pytest

from tests.unit.assistant.tools.kit import BROWSER, LIMIT_CENTS, SORRISO, build_kit
from veranico.modules.pricing.contracts import (
    CoverDefinition,
    IndexDefinition,
    SimulationOptions,
    Window,
)
from veranico.modules.quoting.contracts import CreateQuote, QuoteLocationInput
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId
from veranico.shared.kernel.money import Money

pytestmark = [pytest.mark.req("R-9.4-4"), pytest.mark.req("R-9.4-8")]

COMMAND = CreateQuote(
    location=QuoteLocationInput(
        lat=SORRISO.lat, lon=SORRISO.lon, label="Sorriso", admin_region="Mato Grosso"
    ),
    cover=CoverDefinition(
        index=IndexDefinition(
            index_type="rainfall_below",
            window=Window(start="11-15", end="02-15"),
            trigger=400.0,
            exit=200.0,
        ),
        limit=Money(amount_cents=LIMIT_CENTS),
    ),
    simulation=SimulationOptions(n=100_000, seed=42),
)


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()

    await kit.registry.execute(BROWSER, "price_cover", kit.price_arguments())

    # No idempotency key, and the actor is the agent.
    assert kit.quoting.calls == [("create_quote", (BROWSER, COMMAND, None, "agent"))]


async def test_price_cover_sends_location_cover_and_simulation_without_a_dataset_id() -> None:
    kit = build_kit()
    arguments = {**kit.price_arguments(), "n": 5_000, "seed": 7}

    await kit.registry.execute(BROWSER, "price_cover", arguments)

    [(_, (_, command, _, _))] = kit.quoting.calls
    assert isinstance(command, CreateQuote)
    assert command.simulation == SimulationOptions(n=5_000, seed=7)
    assert command.location == COMMAND.location
    assert command.cover == COMMAND.cover
    # `quoting` resolves the cell and the dataset itself; pricing is not called by the tool.
    assert kit.pricing.calls == []
    assert kit.climate.calls == []
    [definition] = [d for d in kit.registry.definitions() if d.name == "price_cover"]
    properties = definition.input_schema["properties"]
    assert isinstance(properties, dict)
    assert "dataset_id" not in properties

    rejected = await kit.registry.execute(
        BROWSER, "price_cover", {**kit.price_arguments(), "dataset_id": "point:86a8100c7ffffff"}
    )
    assert rejected.error is not None
    assert rejected.error.error_code == "invalid_arguments"
    assert "dataset_id: " in rejected.error.message


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "price_cover", kit.price_arguments())

    assert outcome.ok
    assert outcome.result is not None
    quote = await kit.quoting.get_quote(BROWSER, QuoteId(str(outcome.result["quote_id"])))
    assert outcome.result == {
        "quote_id": quote.quote_id,
        "priced": quote.priced.model_dump(mode="json"),
    }
    assert quote.status == "draft"
    assert [entry.actor for entry in quote.audit] == ["agent"]
    assert outcome.approval is None


async def test_money_params_are_integer_centavos() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "price_cover", kit.price_arguments())

    assert outcome.result is not None
    quote = await kit.quoting.get_quote(BROWSER, QuoteId(str(outcome.result["quote_id"])))
    assert outcome.summary == Coded(
        code="tool.price_cover",
        params={
            "quote_id": quote.quote_id,
            "premium_cents": quote.priced.premium.premium.amount_cents,
        },
    )
    assert type(outcome.summary.params["premium_cents"]) is int


@pytest.mark.req("R-9.4-9")
async def test_missing_limit_is_invalid_arguments_and_creates_no_quote() -> None:
    kit = build_kit()
    arguments = kit.price_arguments()
    del arguments["limit_cents"]

    outcome = await kit.registry.execute(BROWSER, "price_cover", arguments)

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.message.startswith("limit_cents: ")
    assert kit.quoting.calls == []
