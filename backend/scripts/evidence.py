"""Render the measured sections of `docs/verification.md` from stored campaign results.

    uv run python scripts/evidence.py render
    uv run python scripts/evidence.py check --require traceability,mutation,failure,load,evals

A campaign leaves its output under `.evidence/<kind>/<run_id>/` (run ids are UTC timestamps,
so they sort). The kinds are `traceability`, `mutation`, `failure`, `load` and `evals`.

One result file per run, `result.json`:

    {"kind", "run_id", "identity": {"commit": str | null, "dirty": bool}, "measured_at",
     "command", "status": "pass" | "fail", "summary": {...}}

`make load` and the evaluation runner write that file themselves. The other three
campaigns write their own formats (`matrix.json`, `mutants.json`, `req.json`); `render`
converts the newest such run that has no `result.json` yet and writes it next to them. The
identity of a converted run is the state of the tree when it is converted, and both times
are kept: `make evidence` converts right after the campaigns, and a run converted later
says so in the document instead of hiding it.

`render` rewrites only the blocks of the document delimited by

    <!-- evidence:<kind>:begin -->  ...  <!-- evidence:<kind>:end -->

Each block shows exactly one run, the newest of its kind: its identity, date, command,
pass or fail, and its table. Two runs are never combined. A kind with no run renders as
"not run yet". Rendering is a pure function of the result files: it reads no clock and no
Git state, so rendering twice gives the same document.

`check` writes nothing. It exits 1 when the document differs from a fresh render, when a
run has not been converted yet, when a required kind has no result, or when the newest
result of a required kind failed. It also prints every section whose commit is not `HEAD`.

Neither command starts a campaign, and neither calls a model API.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
EVIDENCE = REPOSITORY / ".evidence"
DOCUMENT = REPOSITORY / "docs" / "verification.md"
REQUIREMENTS = BACKEND / "tests" / "requirements.yaml"

KINDS = ("traceability", "mutation", "failure", "load", "evals")
COMMANDS = {
    "traceability": "make traceability",
    "mutation": "make mutation-proof",
    "failure": "make test-failure",
    "load": "make load",
    "evals": "make evals",
}
# The file of a campaign that writes its own format; its presence marks a finished run.
RAW_OUTPUT = {"traceability": "matrix.json", "mutation": "mutants.json", "failure": "req.json"}
FAILURE_SECTION = "16.3"
LATE_CONVERSION_SECONDS = 15 * 60

Result = dict[str, Any]


# --- Reading and converting results ------------------------------------------------------


def run_dirs(evidence: Path, kind: str) -> list[Path]:
    root = evidence / kind
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def newest_result(evidence: Path, kind: str) -> Result | None:
    """The newest run of a kind that has a result file."""
    for run_dir in reversed(run_dirs(evidence, kind)):
        path = run_dir / "result.json"
        if path.is_file():
            result: Result = json.loads(path.read_text(encoding="utf-8"))
            return result
    return None


def unconverted(evidence: Path, kind: str) -> Path | None:
    """The newest run of a kind when it has its own output but no result file yet."""
    raw = RAW_OUTPUT.get(kind)
    runs = run_dirs(evidence, kind)
    if raw is None or not runs:
        return None
    newest = runs[-1]
    if (newest / raw).is_file() and not (newest / "result.json").is_file():
        return newest
    return None


def convert(kind: str, run_dir: Path, identity: dict[str, Any], now: datetime) -> Result:
    raw = run_dir / RAW_OUTPUT[kind]
    measured = datetime.fromtimestamp(raw.stat().st_mtime, tz=UTC)
    status, summary = _CONVERTERS[kind](run_dir)
    result: Result = {
        "kind": kind,
        "run_id": run_dir.name,
        "identity": identity,
        "measured_at": measured.isoformat(timespec="seconds"),
        "command": COMMANDS[kind],
        "status": status,
        "summary": summary,
        "converted_at": now.isoformat(timespec="seconds"),
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def _traceability(run_dir: Path) -> tuple[str, dict[str, Any]]:
    matrix = json.loads((run_dir / "matrix.json").read_text(encoding="utf-8"))
    counts = matrix["summary"]
    return (
        "fail" if counts["failed"] else "pass",
        {
            **counts,
            "not_passed": [
                {key: row[key] for key in ("id", "section", "text", "outcome")}
                for row in matrix["requirements"]
                if row["outcome"] != "passed"
            ],
        },
    )


def _mutation(run_dir: Path) -> tuple[str, dict[str, Any]]:
    proof = json.loads((run_dir / "mutants.json").read_text(encoding="utf-8"))
    summary = {
        key: proof[key]
        for key in ("catalogue_size", "minimum_catalogue_size", "killed", "survived", "stale")
    }
    summary["errors"] = proof["errors"]
    summary["tests"] = proof["tests"]
    summary["mutants"] = [
        {key: mutant.get(key) for key in ("name", "rule", "file", "result", "first_failing_test")}
        for mutant in proof["mutants"]
    ]
    return ("pass" if proof["passed"] else "fail", summary)


def _failure(run_dir: Path) -> tuple[str, dict[str, Any]]:
    """Group the tests of the failure campaign by the SPEC 16.3 scenario they are marked with."""
    tests = json.loads((run_dir / "req.json").read_text(encoding="utf-8"))["tests"]
    requirements = yaml.safe_load(REQUIREMENTS.read_text(encoding="utf-8"))["requirements"]
    scenarios = []
    for requirement in requirements:
        if str(requirement["section"]) != FAILURE_SECTION:
            continue
        mine = [test for test in tests if requirement["id"] in test["req"]]
        scenarios.append(
            {
                "id": requirement["id"],
                "text": requirement["text"],
                "tests": len(mine),
                "passed": sum(1 for test in mine if test["outcome"] == "passed"),
                "failed": sum(1 for test in mine if test["outcome"] == "failed"),
            }
        )
    failed = sum(1 for test in tests if test["outcome"] == "failed")
    unproven = [s["id"] for s in scenarios if s["passed"] == 0 or s["failed"] > 0]
    summary = {
        "tests": len(tests),
        "passed": sum(1 for test in tests if test["outcome"] == "passed"),
        "failed": failed,
        "scenarios": scenarios,
    }
    return ("fail" if failed or unproven or not tests else "pass", summary)


_CONVERTERS = {"traceability": _traceability, "mutation": _mutation, "failure": _failure}


def git_identity(repository: Path = REPOSITORY) -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        done = subprocess.run(
            ["git", *arguments], cwd=repository, capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD") or None, "dirty": status is None or status != ""}


# --- Rendering ---------------------------------------------------------------------------


def identity_text(result: Result) -> str:
    """The short commit when the tree was clean, otherwise `working tree` and the date."""
    identity = result.get("identity") or {}
    commit = identity.get("commit")
    short = f"`{commit[:7]}`" if commit else None
    if short and not identity.get("dirty", True):
        return short
    day = str(result.get("measured_at", ""))[:10] or "unknown date"
    return f"working tree, {day} UTC" + (f", based on {short}" if short else "")


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return lines


def _head(result: Result) -> list[str]:
    status = "PASS" if result["status"] == "pass" else "FAIL"
    lines = [
        f"**{status}** · run `{result['run_id']}` · {identity_text(result)} · "
        f"measured {result['measured_at']} · `{result['command']}`"
    ]
    converted = result.get("converted_at")
    if converted:
        gap = (
            datetime.fromisoformat(converted) - datetime.fromisoformat(result["measured_at"])
        ).total_seconds()
        if gap > LATE_CONVERSION_SECONDS:
            lines += [
                "",
                f"The identity above was recorded {int(gap // 60)} minutes after the run, when "
                "its output was converted. The tree may have changed in between.",
            ]
    return lines


def _render_traceability(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"{summary['requirements']} requirements: {summary['passed']} with a passing test, "
        f"{summary['failed']} with a failing test, {summary['no_passing_test']} with no passing "
        "test.",
    ]
    if summary["not_passed"]:
        lines += ["", "Requirements not proven by this run:", ""]
        lines += _table(
            ["Requirement", "Section", "Statement", "Outcome"],
            [[r["id"], r["section"], r["text"], r["outcome"]] for r in summary["not_passed"]],
        )
    return lines


def _render_mutation(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"{summary['catalogue_size']} mutants (minimum {summary['minimum_catalogue_size']}) "
        f"against `{summary['tests']}`: {summary['killed']} killed, {summary['survived']} "
        f"survived, {summary['stale']} stale, {summary['errors']} errors.",
        "",
    ]
    lines += _table(
        ["Mutant", "Rule it removes", "File", "Result", "First failing test"],
        [
            [
                m["name"],
                m["rule"],
                m["file"],
                m["result"],
                f"`{m['first_failing_test']}`" if m["first_failing_test"] else "none",
            ]
            for m in summary["mutants"]
        ],
    )
    return lines


def _render_failure(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"{summary['tests']} tests: {summary['passed']} passed, {summary['failed']} failed.",
        "",
    ]
    lines += _table(
        ["Scenario", "Statement", "Tests", "Passed", "Failed"],
        [[s["id"], s["text"], s["tests"], s["passed"], s["failed"]] for s in summary["scenarios"]],
    )
    return lines


def _render_load(summary: dict[str, Any]) -> list[str]:
    rows: list[list[object]] = [
        ["Requests scheduled", summary.get("scheduled_requests")],
        ["Evidence lines", summary.get("evidence_lines")],
        ["Distinct idempotency keys", summary.get("distinct_keys")],
        ["`POST /quotes` sends", summary.get("quote_sends")],
        ["… acknowledged", summary.get("quote_sends_acknowledged")],
        ["… refused as back-pressure (429)", summary.get("quote_sends_refused_as_back_pressure")],
        ["Keys acknowledged", summary.get("keys_acknowledged")],
        ["Quotes stored", summary.get("quotes_stored")],
        ["Idempotency records", summary.get("idempotency_records")],
        ["Cells requests answered", f"{summary.get('cells_requests_answered')} of "
         f"{summary.get('cells_requests')}"],
        ["Per-key rate limit of the run, per minute", summary.get("rate_limit_per_key_per_minute")],
    ]  # fmt: skip
    latency_rows: list[list[object]] = []
    lines = _table(["Measure", "Value"], rows)
    latency = summary.get("latency_ms") or {}
    lines += ["", "Latency in milliseconds, as k6 measured it:", ""]
    for name in ("quotes", "cells"):
        measured = latency.get(name) or {}
        latency_rows.append(
            [
                name,
                *(_number(measured.get(key)) for key in ("count", "med", "p(95)", "p(99)", "max")),
            ]
        )
    lines += _table(
        ["Scenario", "Requests", "Median", "p95", "p99", "Maximum"],
        latency_rows,
    )
    lines += ["", "Declared thresholds (load/profile.json):", ""]
    lines += _table(
        ["Metric", "Threshold", "Held"],
        [
            [f"`{metric}`", f"`{expression}`", _held(outcome)]
            for metric, outcomes in (summary.get("thresholds") or {}).items()
            for expression, outcome in outcomes.items()
        ],
    )
    findings = summary.get("findings") or []
    lines += ["", f"Oracle findings: {len(findings)}."]
    lines += [f"- `{finding}`" for finding in findings]
    lines += ["", "What this run is not:", ""]
    lines += [f"- {limit}" for limit in summary.get("limits") or []]
    return lines


def _number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.1f}"
    return "not measured" if value is None else str(value)


def _held(outcome: object) -> str:
    if not isinstance(outcome, dict):
        return "not in the summary"
    return "yes" if outcome.get("ok") is True else "no"


def _ratio(passed: object, total: object) -> str:
    """`53 of 54 (98.1%)`, from the two counts of the summary, never from a stored rate."""
    if not isinstance(passed, int) or not isinstance(total, int) or total <= 0:
        return "not in the summary"
    return f"{passed} of {total} ({100 * passed / total:.1f}%)"


def _render_evals(summary: dict[str, Any]) -> list[str]:
    """The summary written by `tests/evals/run.py` (plan 06)."""
    cases = summary.get("cases")
    cost = summary.get("cost") or {}
    rows: list[list[object]] = [
        ["Model", summary.get("model", "not in the summary")],
        ["Prompt version", summary.get("prompt_version", "not in the summary")],
        ["Cases", len(cases) if isinstance(cases, list) else cases],
        ["Epochs per case", summary.get("epochs")],
        ["Full suite", "yes" if summary.get("full_suite") else "no"],
        ["Sample-epochs passed", _ratio(summary.get("passed"), summary.get("sample_epochs"))],
        ["Required pass rate", f"{summary.get('threshold_percent')}%"],
        ["Cost of the run (agent and grader)", f"US$ {cost.get('cost_usd', 'not measured')}"],
        ["Stopped by the cost limit", "yes" if cost.get("stopped_by_cost_limit") else "no"],
        ["Weather", summary.get("weather", "not in the summary")],
    ]
    lines = _table(["Measure", "Value"], rows)
    per_check = summary.get("per_check") or {}
    if per_check:
        lines += [""]
        lines += _table(
            ["Check", "Passed"],
            [[name, _ratio(c.get("passed"), c.get("total"))] for name, c in per_check.items()],
        )
    failed = summary.get("failed") or []
    if failed:
        lines += ["", "Failed sample-epochs:", ""]
        lines += _table(
            ["Case", "Epoch", "Checks that failed"],
            [[f["case"], f["epoch"], ", ".join(f.get("checks") or [])] for f in failed],
        )
    if isinstance(cases, list):
        lines += ["", "Cases: " + ", ".join(f"`{case}`" for case in cases) + "."]
    return lines


_RENDERERS = {
    "traceability": _render_traceability,
    "mutation": _render_mutation,
    "failure": _render_failure,
    "load": _render_load,
    "evals": _render_evals,
}


def block(kind: str, result: Result | None) -> str:
    """The text between the two markers of a kind."""
    if result is None:
        return f"Not run yet: there is no stored result of `{COMMANDS[kind]}`."
    return "\n".join([*_head(result), "", *_RENDERERS[kind](result["summary"])])


def _markers(kind: str) -> re.Pattern[str]:
    begin, end = f"<!-- evidence:{kind}:begin -->", f"<!-- evidence:{kind}:end -->"
    return re.compile(f"({re.escape(begin)}\n).*?({re.escape(end)})", re.DOTALL)


def render(document: str, evidence: Path) -> str:
    """The document with every evidence block replaced by the newest result of its kind."""
    for kind in KINDS:
        document = _replace_block(document, kind, block(kind, newest_result(evidence, kind)))
    return document


def _replace_block(document: str, kind: str, text: str) -> str:
    def between(found: re.Match[str]) -> str:
        return f"{found[1]}{text}\n{found[2]}"

    return _markers(kind).sub(between, document)


# --- Commands ----------------------------------------------------------------------------


def command_render(evidence: Path, document: Path, now: datetime | None = None) -> int:
    identity = git_identity()
    now = now or datetime.now(UTC)
    for kind in KINDS:
        run_dir = unconverted(evidence, kind)
        if run_dir is not None:
            convert(kind, run_dir, identity, now)
            print(f"evidence: converted {kind} run {run_dir.name}")
    before = document.read_text(encoding="utf-8")
    missing = [kind for kind in KINDS if not _markers(kind).search(before)]
    if missing:
        print(f"evidence: {document} has no block for: {', '.join(missing)}", file=sys.stderr)
        return 1
    after = render(before, evidence)
    if after != before:
        document.write_text(after, encoding="utf-8")
    for kind in KINDS:
        result = newest_result(evidence, kind)
        state = "not run yet" if result is None else f"{result['status']} ({result['run_id']})"
        print(f"evidence: {kind}: {state}")
    return 0


def command_check(evidence: Path, document: Path, required: list[str], head: str | None) -> int:
    problems: list[str] = []
    current = document.read_text(encoding="utf-8")
    if render(current, evidence) != current:
        problems.append(f"{document.name} differs from a fresh render: run `make evidence`")
    for kind in KINDS:
        run_dir = unconverted(evidence, kind)
        if run_dir is not None:
            problems.append(f"{kind}: run {run_dir.name} is not in the document yet")
    for kind in required:
        result = newest_result(evidence, kind)
        if result is None:
            problems.append(f"{kind}: no result (`{COMMANDS[kind]}` has not run)")
        elif result["status"] != "pass":
            problems.append(f"{kind}: the newest run {result['run_id']} failed")
    for kind in KINDS:
        result = newest_result(evidence, kind)
        if result is None:
            continue
        identity = result.get("identity") or {}
        if identity.get("dirty", True) or identity.get("commit") != head:
            print(f"evidence: note: {kind} was measured on {identity_text(result)}, not on HEAD")
    for problem in problems:
        print(f"evidence: {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render or check docs/verification.md.")
    parser.add_argument("command", choices=("render", "check"))
    parser.add_argument("--require", default="", help="comma-separated kinds that must have passed")
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--document", type=Path, default=DOCUMENT)
    options = parser.parse_args(arguments)
    required = [kind for kind in options.require.split(",") if kind]
    unknown = [kind for kind in required if kind not in KINDS]
    if unknown:
        parser.error(f"unknown kind: {', '.join(unknown)}")
    if not options.document.is_file():
        print(f"evidence: {options.document} does not exist", file=sys.stderr)
        return 2
    if options.command == "render":
        return command_render(options.evidence, options.document)
    return command_check(options.evidence, options.document, required, git_identity()["commit"])


if __name__ == "__main__":
    sys.exit(main())
