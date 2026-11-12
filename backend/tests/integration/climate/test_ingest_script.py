"""`scripts/ingest.py`: what it prints and the exit code of each outcome."""

import json

import httpx
import pytest
from scripts.ingest import EXIT_FAILED, EXIT_OK, EXIT_OPEN, ingest

from tests.fakes import builders
from tests.fakes.climate import FakeClimateFacade
from veranico.shared.kernel.errors import OutsideCoverageError, WeatherSourceUnavailableError


async def test_success_prints_the_dataset_as_json_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    climate = FakeClimateFacade()
    dataset = climate.add_series(builders.daily_series())

    code = await ingest(climate, dataset.grid_point.lat, dataset.grid_point.lon)

    assert code == EXIT_OK == 0
    assert json.loads(capsys.readouterr().out) == dataset.model_dump(mode="json")


async def test_no_http_response_exits_three_so_the_gate_reports_open() -> None:
    unreachable = WeatherSourceUnavailableError("no answer")
    unreachable.__cause__ = httpx.ConnectError("scripted")
    climate = FakeClimateFacade()
    climate.fail_with(unreachable)

    assert await ingest(climate, -15.0, -48.0) == EXIT_OPEN == 3


async def test_a_source_that_answers_with_errors_exits_one() -> None:
    climate = FakeClimateFacade()
    climate.fail_with(WeatherSourceUnavailableError("503 four times"))

    assert await ingest(climate, -15.0, -48.0) == EXIT_FAILED == 1


async def test_a_domain_error_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    climate = FakeClimateFacade()
    climate.fail_with(OutsideCoverageError())

    assert await ingest(climate, 38.7, -9.1) == EXIT_FAILED
    assert "outside_coverage" in capsys.readouterr().err
