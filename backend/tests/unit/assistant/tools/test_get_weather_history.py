import pytest

from tests.unit.assistant.tools.kit import BROWSER, SORRISO, build_kit
from veranico.shared.kernel.coded import Coded

pytestmark = [pytest.mark.req("R-9.4-2"), pytest.mark.req("R-9.4-8")]

POINT = {"lat": SORRISO.lat, "lon": SORRISO.lon}


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()

    await kit.registry.execute(BROWSER, "get_weather_history", POINT)

    assert kit.climate.calls == [("ensure_history", (SORRISO.lat, SORRISO.lon))]


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "get_weather_history", POINT)

    assert outcome.ok
    assert outcome.result == kit.dataset.model_dump(mode="json")
    assert outcome.summary == Coded(
        code="tool.get_weather_history",
        params={
            "dataset_id": kit.dataset.dataset_id,
            "first_year": kit.dataset.first_year,
            "last_year": kit.dataset.last_year,
            "source": "synthetic",
        },
    )


async def test_the_result_carries_the_source_so_synthetic_data_is_never_unlabelled() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "get_weather_history", POINT)

    assert outcome.result is not None
    assert outcome.result["source"] == "synthetic"
    [definition] = [d for d in kit.registry.definitions() if d.name == "get_weather_history"]
    assert "synthetic" in definition.description


@pytest.mark.req("R-9.4-9")
async def test_missing_coordinate_is_invalid_arguments() -> None:
    kit = build_kit()

    outcome = await kit.registry.execute(BROWSER, "get_weather_history", {"lat": SORRISO.lat})

    assert outcome.error is not None
    assert outcome.error.error_code == "invalid_arguments"
    assert outcome.error.message.startswith("lon: ")
    assert kit.climate.calls == []
