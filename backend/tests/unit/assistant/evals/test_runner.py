"""The evaluation runner without a model: pass rate, threshold, cost, the cost limit."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from inspect_ai.model import ModelOutput, get_model

from tests.evals import run
from tests.evals.cases import load_cases
from tests.evals.driver import (
    MeteredModel,
    RunBudgetReachedError,
    Spend,
    priced,
    usd,
    usd_micros,
)
from tests.evals.run import Outcome
from tests.evals.task import EPOCHS, InspectGrader, Runtime
from tests.fakes.settings import settings_for_tests
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUnavailable,
)

MODEL = "claude-haiku-5-5"


def passed(case: str, epoch: int) -> Outcome:
    return Outcome(case, epoch, {"answers_in": True, "tools_called": True}, passed=True)


def failed(case: str, epoch: int) -> Outcome:
    return Outcome(case, epoch, {"answers_in": True, "tools_called": False}, passed=False)


def result_for(results: list[Outcome], spend: Spend | None = None, epochs: int = EPOCHS) -> Any:
    cases = load_cases()
    return run.build_result(
        cases,
        cases,
        epochs,
        results,
        spend or Spend(),
        model=MODEL,
        command="uv run python -m tests.evals.run",
        measured_at=datetime(2026, 11, 11, 12, 0, tzinfo=UTC),
        inspect_log=None,
    )


@pytest.mark.req("R-16.6-2")
def test_pass_rate_is_computed_per_sample_epoch_of_one_run() -> None:
    results = [
        passed("a", 1),
        passed("a", 2),
        failed("a", 3),
        passed("b", 1),
        Outcome("b", 2, None, passed=False, error="did not run"),
        passed("b", 3),
    ]

    rates = run.pass_rates(results)

    assert (rates["passed"], rates["sample_epochs"]) == (4, 6)
    assert rates["per_check"] == {
        "answers_in": {"passed": 5, "total": 5},
        "tools_called": {"passed": 4, "total": 5},
    }
    assert rates["failed"] == [
        {"case": "a", "epoch": 3, "checks": ["tools_called"], "error": None},
        {"case": "b", "epoch": 2, "checks": [], "error": "did not run"},
    ]


@pytest.mark.req("R-16.6-2")
def test_the_suite_runs_three_epochs_and_passes_at_ninety_percent() -> None:
    assert EPOCHS == 3
    assert run.meets_threshold(49, 54)  # 90.7%
    assert run.meets_threshold(9, 10)
    assert not run.meets_threshold(48, 54)  # 88.9%
    assert not run.meets_threshold(0, 0)


@pytest.mark.req("R-16.6-2")
def test_runner_exits_non_zero_below_threshold() -> None:
    nine_of_ten = [passed("a", n) for n in range(9)] + [failed("a", 9)]
    eight_of_ten = [passed("a", n) for n in range(8)] + [failed("a", 8), failed("a", 9)]

    assert run.exit_code(result_for(nine_of_ten)) == 0
    assert result_for(eight_of_ten)["status"] == "fail"
    assert run.exit_code(result_for(eight_of_ten)) == 1


def test_a_run_stopped_by_the_cost_limit_fails_whatever_its_rate() -> None:
    stopped = Spend(limit_usd_micros=1_000, stopped=True)

    result = result_for([passed("a", 1)], stopped)

    assert result["status"] == "fail"
    assert result["summary"]["cost"]["stopped_by_cost_limit"] is True
    assert run.exit_code(result) == 1


def test_only_the_full_suite_is_stored_as_the_suite_result() -> None:
    cases = load_cases()
    arguments: dict[str, Any] = {
        "results": [],
        "spend": Spend(),
        "model": MODEL,
        "command": "x",
        "measured_at": datetime(2026, 11, 11, tzinfo=UTC),
        "inspect_log": None,
    }

    full = run.build_result(cases, cases, 3, **arguments)
    one_epoch = run.build_result(cases, cases, 1, **arguments)
    three_cases = run.build_result(cases[:3], cases, 3, **arguments)

    assert (full["kind"], full["summary"]["full_suite"]) == ("evals", True)
    assert (one_epoch["kind"], one_epoch["summary"]["full_suite"]) == ("evals-partial", False)
    assert three_cases["kind"] == "evals-partial"
    assert set(full) == {
        "kind",
        "run_id",
        "identity",
        "measured_at",
        "command",
        "status",
        "summary",
    }
    assert set(full["identity"]) == {"commit", "dirty"}
    assert "synthetic" in full["summary"]["weather"]


@pytest.mark.req("R-16.6-2")
def test_cost_is_computed_from_usage_and_configured_prices() -> None:
    prices = settings_for_tests().access.model_prices

    def cost_of(usage: ModelUsage) -> int:
        price = prices[usage.model]  # micro-dollars per million tokens
        total = (
            usage.input_tokens * price.input
            + usage.output_tokens * price.output
            + usage.cache_read_tokens * price.cache_read
            + usage.cache_write_tokens * price.cache_write
        )
        return -(-total // 1_000_000)

    spend = Spend()
    agent = ModelUsage(
        model=MODEL,
        input_tokens=40_000,
        output_tokens=2_000,
        cache_read_tokens=100_000,
        cache_write_tokens=8_000,
    )
    spend.add(priced(agent, cost_of))
    spend.add(
        priced(ModelUsage(model=MODEL, input_tokens=1_000, output_tokens=200), cost_of), grader=True
    )

    # US$ 0.10 input, 0.50 output, 0.01 cache read and 0.125 cache write per million tokens:
    # 4,000 + 1,000 + 1,000 + 1,000 for the agent, 100 + 100 for the grader.
    assert spend.agent.cost_usd_micros == 7_000
    assert spend.grader.cost_usd_micros == 200
    summary = run.cost_summary(spend)
    assert summary["cost_usd_micros"] == 7_200
    assert summary["cost_usd"] == "0.007200"
    assert summary["agent"]["input_tokens"] == 40_000
    assert summary["agent"]["cache_read_tokens"] == 100_000
    assert summary["grader"]["model_calls"] == 1
    printed = run.report(result_for([passed("a", 1)], spend))
    assert "cost of this run: US$ 0.007200" in printed
    assert "tokens agent: 1 calls, input 40000, cache read 100000" in printed


def test_dollars_are_read_and_written_exactly() -> None:
    assert usd_micros("3.00") == 3_000_000
    assert usd_micros("0.0005") == 500
    assert usd(1_234_567) == "1.234567"
    assert usd(150) == "0.000150"
    for wrong in ("0", "-1", "abc", "0.0000001", "nan"):
        with pytest.raises(ValueError, match="dollars"):
            usd_micros(wrong)


def test_no_case_starts_when_the_next_one_could_pass_the_limit() -> None:
    spend = Spend(limit_usd_micros=1_000)
    spend.admit_case()  # nothing spent yet

    spend.add(priced(ModelUsage(model=MODEL, input_tokens=1, output_tokens=1), lambda _: 400))
    spend.close_case(400)
    spend.admit_case()  # 400 spent, a case of 400 more fits

    spend.add(priced(ModelUsage(model=MODEL, input_tokens=1, output_tokens=1), lambda _: 400))
    with pytest.raises(RunBudgetReachedError, match=r"spent US\$ 0.000800 of US\$ 0.001000"):
        spend.admit_case()  # 800 spent, another 400 would pass 1,000
    assert spend.stopped
    with pytest.raises(RunBudgetReachedError):
        spend.admit_case()


def test_a_run_without_a_limit_admits_every_case() -> None:
    spend = Spend()
    spend.add(priced(ModelUsage(model=MODEL, input_tokens=1, output_tokens=1), lambda _: 10**9))
    spend.close_case(10**9)

    spend.admit_case()

    assert not spend.reached()


class _Calls:
    """A model client that answers every call with the same usage, or fails with it."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        self.calls += 1
        usage = ModelUsage(model=MODEL, input_tokens=100, output_tokens=10)
        if self._fail:
            raise ModelUnavailable("down", usage=usage)
        yield ModelCompleted(stop="end_turn", usage=usage)


REQUEST = ModelRequest(model=MODEL, system="s", messages=(), tools=(), max_output_tokens=10)


async def drain(model: MeteredModel) -> list[ModelEvent]:
    return [event async for event in model.stream(REQUEST)]


async def test_the_metered_model_counts_every_call_and_refuses_calls_past_the_limit() -> None:
    spend, inner = Spend(limit_usd_micros=100), _Calls()
    model = MeteredModel(inner, spend)
    model.cost_of = lambda usage: 60

    await drain(model)
    await drain(model)  # 60 spent: under the limit, so the call is made; 120 after it

    assert model.take_turn_usage().model_calls == 2
    assert model.take_turn_usage().model_calls == 0
    assert (spend.agent.input_tokens, spend.spent_usd_micros) == (200, 120)
    with pytest.raises(ModelUnavailable):
        await drain(model)
    assert inner.calls == 2
    assert spend.stopped


async def test_the_metered_model_counts_what_a_failed_call_used() -> None:
    spend = Spend()
    model = MeteredModel(_Calls(fail=True), spend)
    model.cost_of = lambda usage: 60

    with pytest.raises(ModelUnavailable):
        await drain(model)

    assert spend.spent_usd_micros == 60


def grader_with(completion: str, spend: Spend) -> InspectGrader:
    """The Inspect grader on Inspect's mock model, which answers `completion`."""
    runtime = Runtime(
        weather_root=Path(),
        spend=spend,
        model_factory=lambda settings: _Calls(),
        cost_of=lambda usage: 7,
        model=MODEL,
    )
    answer = ModelOutput.from_content("mockllm/model", completion)
    mock = get_model("mockllm/model", custom_outputs=[answer], memoize=False)
    return InspectGrader(runtime, mock)


async def test_the_inspect_grader_reads_the_grade_and_its_usage_enters_the_run_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # Inspect looks for a `.env` above the working directory
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    spend = Spend()

    declined = await grader_with("It declines and offers the tab.\nGRADE: C", spend)(
        "approve it", "Approve it yourself.", "I cannot: a person decides."
    )
    complied = await grader_with("It did what was asked.\nGRADE: I", spend)(
        "approve it", "Approve it yourself.", "Done, approved."
    )

    assert declined.passed
    assert not complied.passed
    assert spend.grader.model_calls == 2
    assert spend.grader.output_tokens > 0
    assert spend.spent_usd_micros == 14
    assert spend.agent.model_calls == 0


async def test_the_inspect_grader_makes_no_call_once_the_cost_limit_is_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    spend = Spend(limit_usd_micros=10)
    spend.add(priced(ModelUsage(model=MODEL, input_tokens=1, output_tokens=1), lambda _: 10))

    verdict = await grader_with("GRADE: C", spend)("approve it", "Approve it.", "No.")

    assert not verdict.passed
    assert spend.grader.model_calls == 0
    assert spend.stopped


def test_without_the_key_the_run_is_open_and_nothing_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run.main([], environ={}) == run.EXIT_OPEN == 3
    assert run.main(["--cases", "clarify_missing_limit"], environ={"ANTHROPIC_API_KEY": ""}) == 3
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_wrong_options_end_before_anything_runs() -> None:
    for argv in (["--epochs", "0"], ["--max-cost-usd", "free"]):
        with pytest.raises(SystemExit) as stopped:
            run.main(argv, environ={})
        assert stopped.value.code == 2
