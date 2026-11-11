"""The evaluation runner end to end, with a scripted model in place of the paid one.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/assistant/test_evals_run.py -q

Inspect, the harness, the scorers, the cost accounting and the result file run as in a real
run; only the model client and the grader are replaced, so nothing here costs anything.
"""

import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from tests.evals import run
from tests.evals.checks import Verdict
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import ModelCompleted, ModelEvent, ModelRequest
from veranico.modules.assistant.infrastructure.scripted_model import ScriptedModelClient
from veranico.shared.infrastructure.settings import Settings

pytestmark = pytest.mark.integration

HAPPY, CLARIFY = "happy_full_flow_sul_de_minas", "clarify_missing_limit"
# Per model call, at the prices of the test settings: 1,000 input and 100 output tokens.
CALL_USD_MICROS = 150


class PricedScript:
    """The happy path script, reporting usage on every call as the real client does."""

    def __init__(self, settings: Settings) -> None:
        self._script = ScriptedModelClient.happy_path()

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        async for event in self._script.stream(request):
            if isinstance(event, ModelCompleted):
                usage = ModelUsage(model=request.model, input_tokens=1_000, output_tokens=100)
                yield ModelCompleted(stop=event.stop, usage=usage)
            else:
                yield event


async def no_grader(asked: str, request: str, answer: str) -> Verdict:
    raise AssertionError("no case of these runs declares `refuses`")


def result_of(evidence: Path, kind: str) -> dict[str, Any]:
    (path,) = (evidence / kind).glob("*/result.json")
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


@pytest.mark.req("R-16.6-1", "R-16.6-2")
def test_a_run_scores_each_sample_and_reports_rate_tokens_and_cost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environment, directory = dict(os.environ), Path.cwd()

    status = run.main(
        ["--cases", f"{HAPPY},{CLARIFY}", "--epochs", "1"],
        model_factory=PricedScript,
        grader=no_grader,
        log_dir=tmp_path / "logs",
        evidence=tmp_path / "evidence",
    )

    # The script prices whatever it is asked, so the case that had to ask first fails.
    assert status == run.EXIT_FAILED
    result = result_of(tmp_path / "evidence", "evals-partial")
    summary = result["summary"]
    assert result["status"] == "fail"
    assert (summary["cases"], summary["epochs"], summary["full_suite"]) == (
        [HAPPY, CLARIFY],
        1,
        False,
    )
    assert (summary["passed"], summary["sample_epochs"]) == (1, 2)
    assert summary["failed"] == [
        {"case": CLARIFY, "epoch": 1, "checks": ["must_clarify"], "error": None}
    ]
    assert summary["per_check"] == {
        "answers_in": {"passed": 2, "total": 2},
        "must_clarify": {"passed": 0, "total": 1},
        "numbers_grounded": {"passed": 1, "total": 1},
        "tool_args": {"passed": 1, "total": 1},
        "tools_called": {"passed": 1, "total": 1},
    }
    assert "synthetic" in summary["weather"]
    assert summary["prompt_version"].startswith("v")
    # Six model calls for the happy case (two turns), four for the other (one turn).
    cost = summary["cost"]
    assert cost["agent"]["model_calls"] == 10
    assert cost["agent"]["input_tokens"] == 10_000
    assert cost["cost_usd_micros"] == 10 * CALL_USD_MICROS
    assert cost["cost_usd"] == "0.001500"
    assert cost["stopped_by_cost_limit"] is False
    assert list((tmp_path / "logs").glob("*.eval"))
    printed = capsys.readouterr().out
    assert "pass rate: 1/2 sample-epochs = 50.0%" in printed
    assert "cost of this run: US$ 0.001500" in printed
    # Inspect would load the nearest `.env` into the environment; the runner prevents it.
    # The application's Firestore client sets the emulator variable its SDK reads.
    assert set(os.environ) - set(environment) <= {"FIRESTORE_EMULATOR_HOST"}
    assert Path.cwd() == directory


def test_the_cost_limit_stops_the_run_and_the_run_fails(tmp_path: Path) -> None:
    status = run.main(
        ["--cases", HAPPY, "--epochs", "2", "--max-cost-usd", "0.0005"],
        model_factory=PricedScript,
        grader=no_grader,
        log_dir=tmp_path / "logs",
        evidence=tmp_path / "evidence",
    )

    assert status == run.EXIT_FAILED
    summary = result_of(tmp_path / "evidence", "evals-partial")["summary"]
    cost = summary["cost"]
    assert cost["stopped_by_cost_limit"] is True
    # The limit of 500 was reached by the fourth call; the fifth was refused, and the
    # second epoch never called the model.
    assert cost["agent"]["model_calls"] == 4
    assert cost["cost_usd_micros"] == 4 * CALL_USD_MICROS
    assert (summary["passed"], summary["sample_epochs"]) == (0, 2)
    assert [failed["epoch"] for failed in summary["failed"]] == [1, 2]
    assert all(failed["error"] for failed in summary["failed"])
