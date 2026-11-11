import pytest

from tests.unit.assistant.tools.kit import BROWSER, build_kit
from veranico.modules.pricing.contracts import Window
from veranico.shared.kernel.coded import Coded

pytestmark = [pytest.mark.req("R-9.4-5"), pytest.mark.req("R-9.4-8")]


def arguments(dataset_id: str, **overrides: object) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "index_type": "dry_spell_above",
        "window_start": "09-01",
        "window_end": "10-31",
        "top_n": 3,
        **overrides,
    }


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()

    await kit.registry.execute(BROWSER, "find_extreme_seasons", arguments(kit.dataset.dataset_id))

    assert kit.pricing.calls == [
        (
            "extreme_seasons",
            (kit.dataset.dataset_id, "dry_spell_above", Window(start="09-01", end="10-31"), 3),
        )
    ]


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(
        BROWSER, "find_extreme_seasons", arguments(kit.dataset.dataset_id)
    )

    expected = await kit.pricing.extreme_seasons(
        kit.dataset.dataset_id, "dry_spell_above", Window(start="09-01", end="10-31"), 3
    )
    assert outcome.ok
    assert outcome.result == {"seasons": [season.model_dump(mode="json") for season in expected]}
    assert outcome.summary == Coded(code="tool.find_extreme_seasons", params={"count": 3})


@pytest.mark.req("R-9.4-9")
@pytest.mark.parametrize("top_n", [0, 11])
async def test_top_n_outside_one_to_ten_is_invalid_arguments(top_n: int) -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(
        BROWSER, "find_extreme_seasons", arguments(kit.dataset.dataset_id, top_n=top_n)
    )

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.message.startswith("top_n: ")
    assert kit.pricing.calls == []
