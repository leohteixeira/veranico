"""Shared pytest configuration: the requirement report read by `scripts/traceability.py`.

`--req-report=<path>` writes one JSON document covering every test that ran:

    {"tests": [{"id": "<node id>", "req": ["R-5.3-1"], "outcome": "passed"}]}

`req` holds the identifiers of the test's `@pytest.mark.req(...)` markers (empty when it has
none) and `outcome` is `passed`, `failed` or `skipped`. Deselected tests are not listed.
"""

import json
import os
from pathlib import Path

import pytest

_OPTION = "--req-report"
_PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "EARTHENGINE_PROJECT")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        _OPTION,
        metavar="PATH",
        default=None,
        help="write each test's node id, requirement identifiers and outcome as JSON",
    )


def pytest_configure(config: pytest.Config) -> None:
    # The Makefile exports the owner's keys to its recipes. No test may reach a keyed or paid
    # service (goal.md section 3), so the keys never enter a test process: a test that needs
    # a value sets its own. The evaluation runner is not a pytest run and keeps its key.
    for name in _PROVIDER_KEYS:
        os.environ.pop(name, None)
    path = config.getoption(_OPTION)
    if path is not None:
        config.pluginmanager.register(_RequirementReport(Path(path)), "veranico-req-report")


class _RequirementReport:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._requirements: dict[str, list[str]] = {}
        self._phases: dict[str, list[tuple[str, str]]] = {}

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            identifiers = {str(arg) for marker in item.iter_markers("req") for arg in marker.args}
            self._requirements[item.nodeid] = sorted(identifiers)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._phases.setdefault(report.nodeid, []).append((report.when or "", report.outcome))

    def pytest_sessionfinish(self) -> None:
        tests = [
            {
                "id": node_id,
                "req": self._requirements.get(node_id, []),
                "outcome": _outcome(phases),
            }
            for node_id, phases in sorted(self._phases.items())
        ]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"tests": tests}, indent=2) + "\n", encoding="utf-8")


def _outcome(phases: list[tuple[str, str]]) -> str:
    """A failure in any phase fails the test; otherwise the call phase decides."""
    if any(outcome == "failed" for _, outcome in phases):
        return "failed"
    if any(when == "call" and outcome == "passed" for when, outcome in phases):
        return "passed"
    return "skipped"
