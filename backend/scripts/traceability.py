"""Build the requirement-to-test matrix from `tests/requirements.yaml` and test reports.

    uv run pytest tests -q --req-report=.cache/req.json
    uv run python scripts/traceability.py --check-ids --report .cache/req.json
    uv run python scripts/traceability.py --matrix --report a.json --report b.json
    uv run python scripts/traceability.py --require-all --report a.json --json matrix.json

A report is what `pytest --req-report` writes: `{"tests": [{"id", "req", "outcome"}]}`.
Any file in that shape is accepted, for example `frontend/.cache/req.json`. Several reports
are merged; a test listed in more than one report counts once per report.

`--check-ids`   fail when a test names an identifier that is not in the requirements file
`--matrix`      print requirement, statement, tests and outcome as a Markdown table
`--json PATH`   write the same matrix as JSON
`--require-all` fail when a requirement has no passing test, or has a failing one

Outcome of a requirement: `failed` when any of its tests failed, `passed` when at least one
passed and none failed, otherwise `no passing test`.

Exit codes: 0 success, 1 a check failed, 2 the input could not be read.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REQUIREMENTS = Path(__file__).resolve().parent.parent / "tests" / "requirements.yaml"
OUTCOMES = {"passed", "failed", "skipped"}


class InputError(Exception):
    """A requirements file or a report that cannot be read as what it should be."""


@dataclass(frozen=True)
class Requirement:
    identifier: str
    section: str
    text: str
    plan: str


@dataclass(frozen=True)
class TestResult:
    identifier: str
    requirements: tuple[str, ...]
    outcome: str


def load_requirements(path: Path) -> list[Requirement]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return [
            Requirement(entry["id"], entry["section"], entry["text"], entry["plan"])
            for entry in loaded["requirements"]
        ]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as error:
        raise InputError(f"{path}: not a requirements file ({error!r})") from error


def load_report(path: Path) -> list[TestResult]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        results = [
            TestResult(str(test["id"]), tuple(str(item) for item in test["req"]), test["outcome"])
            for test in loaded["tests"]
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise InputError(f"{path}: not a requirement report ({error!r})") from error
    unknown = sorted({result.outcome for result in results} - OUTCOMES)
    if unknown:
        raise InputError(f"{path}: unknown outcome {unknown}")
    return results


def unknown_identifiers(
    requirements: list[Requirement], results: list[TestResult]
) -> list[tuple[str, str]]:
    """(identifier, test) for every marker that names no requirement of the file."""
    known = {requirement.identifier for requirement in requirements}
    return [
        (identifier, result.identifier)
        for result in results
        for identifier in result.requirements
        if identifier not in known
    ]


def outcome_of(results: list[TestResult]) -> str:
    outcomes = {result.outcome for result in results}
    if "failed" in outcomes:
        return "failed"
    if "passed" in outcomes:
        return "passed"
    return "no passing test"


def build_matrix(
    requirements: list[Requirement], results: list[TestResult]
) -> list[tuple[Requirement, list[TestResult], str]]:
    by_requirement: dict[str, list[TestResult]] = {}
    for result in results:
        for identifier in result.requirements:
            by_requirement.setdefault(identifier, []).append(result)
    rows = []
    for requirement in requirements:
        tests = sorted(
            by_requirement.get(requirement.identifier, []), key=lambda test: test.identifier
        )
        rows.append((requirement, tests, outcome_of(tests)))
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def as_markdown(rows: list[tuple[Requirement, list[TestResult], str]]) -> str:
    lines = ["| Requirement | Statement | Tests | Outcome |", "|---|---|---|---|"]
    for requirement, tests, outcome in rows:
        listed = "<br>".join(f"`{_cell(test.identifier)}`" for test in tests) or "none"
        lines.append(
            f"| {requirement.identifier} | {_cell(requirement.text)} | {listed} | {outcome} |"
        )
    return "\n".join(lines) + "\n"


def as_json(rows: list[tuple[Requirement, list[TestResult], str]]) -> dict[str, Any]:
    outcomes = [outcome for _, _, outcome in rows]
    return {
        "summary": {
            "requirements": len(rows),
            "passed": outcomes.count("passed"),
            "failed": outcomes.count("failed"),
            "no_passing_test": outcomes.count("no passing test"),
        },
        "requirements": [
            {
                "id": requirement.identifier,
                "section": requirement.section,
                "text": requirement.text,
                "plan": requirement.plan,
                "outcome": outcome,
                "tests": [{"id": test.identifier, "outcome": test.outcome} for test in tests],
            }
            for requirement, tests, outcome in rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--report", type=Path, action="append", default=[], metavar="PATH")
    parser.add_argument("--check-ids", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--json", type=Path, default=None, metavar="PATH")
    parser.add_argument("--require-all", action="store_true")
    arguments = parser.parse_args()

    try:
        if not arguments.report:
            raise InputError("give at least one --report")
        requirements = load_requirements(arguments.requirements)
        results = [result for path in arguments.report for result in load_report(path)]
    except InputError as error:
        print(f"traceability: {error}", file=sys.stderr)
        return 2

    rows = build_matrix(requirements, results)
    failed = False
    if arguments.check_ids:
        for identifier, test in unknown_identifiers(requirements, results):
            print(f"traceability: unknown requirement {identifier} in {test}", file=sys.stderr)
            failed = True
    if arguments.matrix:
        sys.stdout.write(as_markdown(rows))
    if arguments.json is not None:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(as_json(rows), indent=2) + "\n", encoding="utf-8")
    if arguments.require_all:
        for requirement, _, outcome in rows:
            if outcome != "passed":
                print(f"traceability: {requirement.identifier}: {outcome}", file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
