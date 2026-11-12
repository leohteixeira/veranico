import pytest

from tests.fakes import builders
from tests.unit.assistant.tools.kit import BROWSER, INDEX_ARGUMENTS, LIMIT_CENTS, build_kit
from veranico.modules.pricing.contracts import CoverDefinition, IndexDefinition, Window
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.money import Money

pytestmark = [pytest.mark.req("R-9.4-3"), pytest.mark.req("R-9.4-8")]

COVER = CoverDefinition(
    index=IndexDefinition(
        index_type="rainfall_below",
        window=Window(start="11-15", end="02-15"),
        trigger=400.0,
        exit=200.0,
    ),
    limit=Money(amount_cents=LIMIT_CENTS),
)


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()
    arguments = {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "limit_cents": LIMIT_CENTS,
    }

    await kit.registry.execute(BROWSER, "backtest_index", arguments)

    # The flat fields become a `CoverDefinition`; the limit stays integer centavos.
    assert kit.pricing.calls == [("backtest", (kit.dataset.dataset_id, COVER))]


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()
    arguments = {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "limit_cents": LIMIT_CENTS,
    }

    outcome = await kit.registry.execute(BROWSER, "backtest_index", arguments)

    expected = builders.backtest_result(
        COVER,
        dataset_id=kit.dataset.dataset_id,
        first_season=kit.dataset.first_year,
        seasons=kit.dataset.last_year - kit.dataset.first_year + 1,
    )
    assert outcome.ok
    assert outcome.result == expected.model_dump(mode="json")
    assert outcome.summary == Coded(
        code="tool.backtest_index",
        params={
            "seasons_used": expected.seasons_used,
            "trigger_frequency_rate": expected.trigger_frequency,
        },
    )


async def test_it_persists_nothing() -> None:
    kit = build_kit()
    arguments = {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "limit_cents": LIMIT_CENTS,
    }

    await kit.registry.execute(BROWSER, "backtest_index", arguments)

    assert kit.quoting.calls == []


@pytest.mark.req("R-9.4-9")
async def test_malformed_window_and_fractional_limit_are_invalid_arguments() -> None:
    kit = build_kit()
    arguments = {
        "dataset_id": kit.dataset.dataset_id,
        **INDEX_ARGUMENTS,
        "window_start": "15/11",
        "limit_cents": 300000.5,
    }

    outcome = await kit.registry.execute(BROWSER, "backtest_index", arguments)

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert "window_start: " in outcome.error.message
    assert "limit_cents: " in outcome.error.message
    assert kit.pricing.calls == []
