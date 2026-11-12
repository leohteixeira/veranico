"""Run the evaluation suite of SPEC 16.6 against the real model and report what it cost.

    make evals
    uv run python -m tests.evals.run [--cases a,b,c] [--epochs N] [--max-cost-usd X]

This calls the paid model API. It needs `ANTHROPIC_API_KEY` in the environment and the
emulators (`docker compose -p veranico up -d --wait firestore storage`). The model client is
always the Anthropic one, whatever the settings select, on the model of `AGENT_MODEL`.

Without options: all 18 cases, 3 epochs. `--cases` and `--epochs` run a part of the suite, for
example a first measuring run of three cases and one epoch. `--max-cost-usd` is a hard stop
(default US$ 3.00): no case starts when what is spent plus the most expensive case so far
would pass it, and no model call is made once it is reached. A stopped run fails.

Every run prints and stores its identity (commit, or `working tree` with the date), the pass
rate overall and per check, the tokens and the cost in US dollars: measured token usage of
every model call, the grader's included, times the configured prices
(`AccessFacade.cost_of`). Pass rates of different runs are never added up.

The weather under the cases is generated on purpose (seeded synthetic cubes, even though the
real cubes exist since human gate H1), so a result never depends on real weather: the suite
measures how the agent behaves, and its figures are not real weather history.

Output: Inspect logs under `tests/evals/logs/`; the run summary as
`.evidence/evals/<run_id>/result.json`, or under `.evidence/evals-partial/` when the run was
not the full suite, so that a partial run is never taken for the suite's result.

Exit codes: 0 the pass rate is at or above 90% and the run was complete; 1 below, stopped by
the cost limit, or failed to run; 3 `ANTHROPIC_API_KEY` is missing (reported as open by
`gate.py`).
"""

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import EvalLog

from tests.evals.cases import Case, CasesFileError, load_cases, select
from tests.evals.driver import Spend, usd, usd_micros
from tests.evals.harness import (
    CUBE_SEED,
    EmulatorDownError,
    install_synthetic_cubes,
    require_emulators,
)
from tests.evals.task import EPOCHS, Grader, Runtime, sample_passed, veranico_task
from veranico.modules.assistant.application.ports import ModelClient
from veranico.modules.assistant.application.prompt import load_system_prompt
from veranico.modules.assistant.infrastructure.anthropic_model import AnthropicModelClient
from veranico.shared.infrastructure.settings import Settings

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
LOGS = Path(__file__).resolve().parent / "logs"
EVIDENCE = REPOSITORY / ".evidence"
KEY_VARIABLE = "ANTHROPIC_API_KEY"
THRESHOLD_PERCENT = 90
DEFAULT_MAX_COST_USD = "3.00"
WEATHER = (
    f"synthetic cubes (generated, seed {CUBE_SEED}) of the three showcase regions; "
    "not real weather history"
)
EXIT_PASSED, EXIT_FAILED, EXIT_OPEN = 0, 1, 3

ModelFactory = Callable[[Settings], ModelClient]


@dataclass(frozen=True)
class Outcome:
    """One sample-epoch: which declared checks passed. `checks` is None when it did not run
    to the end (an error, or the cost limit)."""

    case_id: str
    epoch: int
    checks: Mapping[str, bool] | None
    passed: bool
    error: str | None = None


def outcomes(log: EvalLog, cases: Sequence[Case], epochs: int) -> list[Outcome]:
    """One outcome per case and epoch of the run; a sample the log lacks did not pass."""
    by_id = {case.id: case for case in cases}
    found = {(str(sample.id), sample.epoch): sample for sample in log.samples or []}
    result = []
    for case in cases:
        for epoch in range(1, epochs + 1):
            sample = found.get((case.id, epoch))
            if sample is None:
                result.append(Outcome(case.id, epoch, None, passed=False, error="did not run"))
            elif sample.error is not None:
                message = sample.error.message.strip().splitlines()
                error = message[0] if message else "error"
                result.append(Outcome(case.id, epoch, None, passed=False, error=error))
            else:
                scores = sample.scores or {}
                checks = {
                    name: name in scores and scores[name].value == "C"
                    for name in by_id[case.id].checks
                }
                passed = sample_passed(by_id[case.id], scores)
                result.append(Outcome(case.id, epoch, checks, passed=passed))
    return result


def pass_rates(results: Sequence[Outcome]) -> dict[str, Any]:
    """Passed sample-epochs over all sample-epochs of this one run, overall and per check."""
    per_check: dict[str, dict[str, int]] = {}
    for outcome in results:
        for name, passed in (outcome.checks or {}).items():
            counts = per_check.setdefault(name, {"passed": 0, "total": 0})
            counts["total"] += 1
            counts["passed"] += int(passed)
    return {
        "sample_epochs": len(results),
        "passed": sum(outcome.passed for outcome in results),
        "per_check": dict(sorted(per_check.items())),
        "failed": [
            {
                "case": outcome.case_id,
                "epoch": outcome.epoch,
                "checks": sorted(n for n, ok in (outcome.checks or {}).items() if not ok),
                "error": outcome.error,
            }
            for outcome in results
            if not outcome.passed
        ],
    }


def meets_threshold(passed: int, total: int) -> bool:
    """At or above 90%, in whole numbers."""
    return total > 0 and passed * 100 >= THRESHOLD_PERCENT * total


def percent(passed: int, total: int) -> str:
    return f"{passed * 100 / total:.1f}%" if total else "n/a"


def cost_summary(spend: Spend) -> dict[str, Any]:
    """Measured token usage and its cost at the configured prices."""
    return {
        "cost_usd": usd(spend.spent_usd_micros),
        "cost_usd_micros": spend.spent_usd_micros,
        "max_cost_usd": usd(spend.limit_usd_micros) if spend.limit_usd_micros else None,
        "stopped_by_cost_limit": spend.stopped,
        "agent": spend.agent.model_dump(),
        "grader": spend.grader.model_dump(),
    }


def status_of(summary: Mapping[str, Any]) -> str:
    complete = not summary["cost"]["stopped_by_cost_limit"]
    passed = meets_threshold(summary["passed"], summary["sample_epochs"])
    return "pass" if complete and passed else "fail"


def exit_code(result: Mapping[str, Any]) -> int:
    return EXIT_PASSED if result["status"] == "pass" else EXIT_FAILED


def identity() -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        done = subprocess.run(
            ["git", *arguments], cwd=REPOSITORY, capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"commit": commit or None, "dirty": status is None or status != ""}


def identity_line(who: Mapping[str, Any], measured_at: datetime) -> str:
    commit = who["commit"]
    if commit and not who["dirty"]:
        return str(commit)[:12]
    base = f" on {str(commit)[:12]}" if commit else ""
    return f"working tree{base}, {measured_at:%Y-%m-%d} UTC"


def report(result: Mapping[str, Any]) -> str:
    summary, cost = result["summary"], result["summary"]["cost"]
    agent, grader = cost["agent"], cost["grader"]
    lines = [
        f"evals {result['status']}: run {result['run_id']}, "
        f"{identity_line(result['identity'], datetime.fromisoformat(result['measured_at']))}",
        f"  model {summary['model']}, prompt {summary['prompt_version']}, "
        f"{len(summary['cases'])} cases x {summary['epochs']} epochs"
        + ("" if summary["full_suite"] else " (not the full suite)"),
        f"  weather: {summary['weather']}",
        f"  pass rate: {summary['passed']}/{summary['sample_epochs']} sample-epochs "
        f"= {percent(summary['passed'], summary['sample_epochs'])} "
        f"(threshold {THRESHOLD_PERCENT}%)",
    ]
    for name, counts in summary["per_check"].items():
        lines.append(
            f"    {name}: {counts['passed']}/{counts['total']} "
            f"= {percent(counts['passed'], counts['total'])}"
        )
    for failed in summary["failed"]:
        why = failed["error"] or ", ".join(failed["checks"])
        lines.append(f"    failed {failed['case']} epoch {failed['epoch']}: {why}")
    for name, used in (("agent", agent), ("grader", grader)):
        lines.append(
            f"  tokens {name}: {used['model_calls']} calls, input {used['input_tokens']}, "
            f"cache read {used['cache_read_tokens']}, cache write {used['cache_write_tokens']}, "
            f"output {used['output_tokens']}, US$ {usd(used['cost_usd_micros'])}"
        )
    lines.append(
        f"  cost of this run: US$ {cost['cost_usd']}"
        + (f" (limit US$ {cost['max_cost_usd']})" if cost["max_cost_usd"] else "")
        + (" - STOPPED BY THE COST LIMIT" if cost["stopped_by_cost_limit"] else "")
    )
    return "\n".join(lines)


@contextlib.contextmanager
def _away_from_dotenv() -> Iterator[None]:
    """Inspect loads the nearest `.env` above the working directory into the environment.

    This runner takes its key from the environment it was started with and must not read
    that file, so the evaluation runs from an empty directory with python-dotenv switched off.
    """
    previous = os.environ.get("PYTHON_DOTENV_DISABLED")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    try:
        with (
            tempfile.TemporaryDirectory(prefix="veranico-evals-cwd-") as empty,
            contextlib.chdir(empty),
        ):
            yield
    finally:
        if previous is None:
            os.environ.pop("PYTHON_DOTENV_DISABLED", None)
        else:
            os.environ["PYTHON_DOTENV_DISABLED"] = previous


def evaluate(
    cases: list[Case],
    epochs: int,
    spend: Spend,
    *,
    model_factory: ModelFactory,
    grader: Grader | None,
    log_dir: Path,
    settings_overrides: Mapping[str, Any] | None = None,
) -> tuple[EvalLog, Runtime]:
    """One Inspect run of `cases`, one sample at a time, on freshly generated cubes."""
    with tempfile.TemporaryDirectory(prefix="veranico-evals-weather-") as weather:
        install_synthetic_cubes(Path(weather))
        runtime = Runtime(
            weather_root=Path(weather),
            spend=spend,
            model_factory=model_factory,
            grader=grader,
            settings_overrides=settings_overrides,
        )
        with _away_from_dotenv():
            logs = inspect_eval(
                veranico_task(cases, runtime),
                model=None,
                epochs=epochs,
                log_dir=str(log_dir.resolve()),
                display="none",
                max_samples=1,
                fail_on_error=False,
            )
    return logs[0], runtime


def build_result(
    cases: Sequence[Case],
    all_cases: Sequence[Case],
    epochs: int,
    results: Sequence[Outcome],
    spend: Spend,
    *,
    model: str,
    command: str,
    measured_at: datetime,
    inspect_log: str | None,
) -> dict[str, Any]:
    full_suite = len(cases) == len(all_cases) and epochs == EPOCHS
    summary = {
        "cases": [case.id for case in cases],
        "epochs": epochs,
        "full_suite": full_suite,
        **pass_rates(results),
        "threshold_percent": THRESHOLD_PERCENT,
        "model": model,
        "prompt_version": load_system_prompt().version,
        "weather": WEATHER,
        "cost": cost_summary(spend),
        "inspect_log": inspect_log,
    }
    return {
        "kind": "evals" if full_suite else "evals-partial",
        "run_id": measured_at.strftime("%Y%m%dT%H%M%SZ"),
        "identity": identity(),
        "measured_at": measured_at.isoformat(timespec="seconds"),
        "command": command,
        "status": status_of(summary),
        "summary": summary,
    }


def write_result(result: Mapping[str, Any], evidence: Path = EVIDENCE) -> Path:
    directory = evidence / str(result["kind"]) / str(result["run_id"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "result.json"
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return path


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tests.evals.run", description=__doc__)
    parser.add_argument("--cases", help="comma-separated case identifiers; default: all")
    parser.add_argument("--epochs", type=int, default=EPOCHS, help=f"default {EPOCHS}")
    parser.add_argument(
        "--max-cost-usd",
        default=DEFAULT_MAX_COST_USD,
        help=f"hard stop for the cost of this run, in US dollars (default {DEFAULT_MAX_COST_USD})",
    )
    arguments = parser.parse_args(argv)
    if arguments.epochs < 1:
        parser.error("--epochs must be at least 1")
    try:
        arguments.max_cost_usd_micros = usd_micros(arguments.max_cost_usd)
    except ValueError as error:
        parser.error(str(error))
    return arguments


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    model_factory: ModelFactory | None = None,
    grader: Grader | None = None,
    log_dir: Path = LOGS,
    evidence: Path = EVIDENCE,
) -> int:
    """`model_factory` and `grader` exist for the tests: they replace the paid model."""
    argv = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(argv)
    environ = os.environ if environ is None else environ
    if model_factory is None and not environ.get(KEY_VARIABLE):
        print(
            f"evals: open, {KEY_VARIABLE} is not set: the suite needs the model API",
            file=sys.stderr,
        )
        return EXIT_OPEN
    try:
        all_cases = load_cases()
        chosen = arguments.cases.split(",") if arguments.cases else None
        cases = select(all_cases, chosen)
        require_emulators()
    except (CasesFileError, EmulatorDownError) as error:
        print(f"evals: failed, {error}", file=sys.stderr)
        return EXIT_FAILED

    measured_at = datetime.now(UTC)
    spend = Spend(limit_usd_micros=arguments.max_cost_usd_micros)
    print(
        f"evals: {len(cases)} cases x {arguments.epochs} epochs on synthetic cubes, "
        f"cost limit US$ {usd(arguments.max_cost_usd_micros)}",
        flush=True,
    )
    log, runtime = evaluate(
        cases,
        arguments.epochs,
        spend,
        model_factory=model_factory or AnthropicModelClient.from_settings,
        grader=grader,
        log_dir=log_dir,
        # The paid client, whatever the environment selects.
        settings_overrides=None if model_factory else {"assistant": {"model_client": "anthropic"}},
    )
    result = build_result(
        cases,
        all_cases,
        arguments.epochs,
        outcomes(log, cases, arguments.epochs),
        spend,
        model=runtime.model,
        command=" ".join(["uv run python -m tests.evals.run", *argv]),
        measured_at=measured_at,
        inspect_log=log.location,
    )
    path = write_result(result, evidence)
    print(report(result))
    print(f"  result: {path}")
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
