"""`scripts/evidence.py`: the measured blocks of `docs/verification.md`, from fixture results."""

import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "evidence.py"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evidence_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load()

DOCUMENT = "\n".join(
    ["# Verification", "", "Written by hand, before."]
    + [
        line
        for kind in evidence.KINDS
        for line in (
            f"## {kind}",
            f"<!-- evidence:{kind}:begin -->",
            "stale text",
            f"<!-- evidence:{kind}:end -->",
            "",
        )
    ]
    + ["Written by hand, after.", ""]
)

LOAD_SUMMARY: dict[str, Any] = {
    "scheduled_requests": 1600,
    "evidence_lines": 1600,
    "distinct_keys": 200,
    "quote_sends": 1000,
    "quote_sends_acknowledged": 1000,
    "quote_sends_refused_as_back_pressure": 0,
    "keys_acknowledged": 200,
    "quotes_stored": 200,
    "idempotency_records": 200,
    "cells_requests": 600,
    "cells_requests_answered": 600,
    "rate_limit_per_key_per_minute": 600000,
    "latency_ms": {
        "quotes": {"count": 1000, "med": 81.25, "p(95)": 412.5, "p(99)": 700.0, "max": 912.0},
        "cells": {"count": 600, "med": 20.0, "p(95)": 95.0, "p(99)": 130.0, "max": 150.0},
    },
    "thresholds": {
        "http_req_duration{scenario:quotes}": {"p(95)<2000": {"ok": True}},
        "http_req_duration{scenario:cells}": {"p(95)<1000": {"ok": True}},
    },
    "findings": [],
    "limits": ["Generator and service shared one host.", "Not a capacity estimate."],
}


def result(kind: str, run_id: str, summary: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "run_id": run_id,
        "identity": {"commit": COMMIT, "dirty": False},
        "measured_at": "2026-11-11T12:00:00+00:00",
        "command": evidence.COMMANDS[kind],
        "status": "pass",
        "summary": summary,
        **changes,
    }


def store(root: Path, stored: dict[str, Any]) -> None:
    run_dir = root / stored["kind"] / stored["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(json.dumps(stored), encoding="utf-8")


def raw_run(root: Path, kind: str, run_id: str, content: dict[str, Any]) -> Path:
    run_dir = root / kind / run_id
    run_dir.mkdir(parents=True)
    path = run_dir / evidence.RAW_OUTPUT[kind]
    path.write_text(json.dumps(content), encoding="utf-8")
    measured = datetime(2026, 11, 11, 12, 0, tzinfo=UTC).timestamp()
    os.utime(path, (measured, measured))
    return run_dir


def block_of(document: str, kind: str) -> str:
    begin, end = f"<!-- evidence:{kind}:begin -->\n", f"<!-- evidence:{kind}:end -->"
    return document.split(begin)[1].split(end)[0]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / ".evidence"


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "verification.md"
    path.write_text(DOCUMENT, encoding="utf-8")
    return path


def test_a_kind_without_a_run_renders_as_not_run_yet(root: Path) -> None:
    rendered = evidence.render(DOCUMENT, root)

    for kind in evidence.KINDS:
        assert "Not run yet" in block_of(rendered, kind)
        assert "stale text" not in block_of(rendered, kind)
    assert "`make evals`" in block_of(rendered, "evals")


def test_only_the_blocks_change(root: Path) -> None:
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY))

    rendered = evidence.render(DOCUMENT, root)

    assert rendered.startswith("# Verification\n\nWritten by hand, before.\n")
    assert rendered.endswith("Written by hand, after.\n")
    assert evidence.render(rendered, root) == rendered  # rendering twice changes nothing


def test_the_load_block_shows_identity_counts_latency_thresholds_and_limits(root: Path) -> None:
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY))

    text = block_of(evidence.render(DOCUMENT, root), "load")

    assert text.startswith(
        "**PASS** · run `20261111T120000Z` · `0123456` · measured 2026-11-11T12:00:00+00:00"
        " · `make load`"
    )
    assert "| Quotes stored | 200 |" in text
    assert "| quotes | 1000 | 81.2 | 412.5 | 700.0 | 912.0 |" in text
    assert "| `http_req_duration{scenario:cells}` | `p(95)<1000` | yes |" in text
    assert "Oracle findings: 0." in text
    assert "- Not a capacity estimate." in text


MINIMAL_SUMMARIES: dict[str, dict[str, Any]] = {
    "traceability": {
        "requirements": 1,
        "passed": 1,
        "failed": 0,
        "no_passing_test": 0,
        "not_passed": [],
    },
    "mutation": {
        "catalogue_size": 0,
        "minimum_catalogue_size": 0,
        "tests": "tests/unit/pricing",
        "killed": 0,
        "survived": 0,
        "stale": 0,
        "errors": 0,
        "mutants": [],
    },
    "failure": {"tests": 0, "passed": 0, "failed": 0, "scenarios": []},
    "load": LOAD_SUMMARY,
    "evals": {},
}


@pytest.mark.req("R-16.8-2")
def test_the_result_of_every_kind_names_the_commit_it_was_measured_on(root: Path) -> None:
    assert set(MINIMAL_SUMMARIES) == set(evidence.KINDS)
    for kind, summary in MINIMAL_SUMMARIES.items():
        store(root, result(kind, "20261111T120000Z", summary))

    rendered = evidence.render(DOCUMENT, root)

    for kind in evidence.KINDS:
        head = block_of(rendered, kind).splitlines()[0]
        assert "run `20261111T120000Z` · `0123456` · measured" in head, kind


@pytest.mark.req("R-16.8-2")
def test_a_result_measured_on_a_changed_tree_names_the_commit_it_was_based_on(root: Path) -> None:
    dirty = {"commit": COMMIT, "dirty": True}
    for kind, summary in MINIMAL_SUMMARIES.items():
        store(root, result(kind, "20261111T120000Z", summary, identity=dirty))

    rendered = evidence.render(DOCUMENT, root)

    for kind in evidence.KINDS:
        head = block_of(rendered, kind).splitlines()[0]
        assert "working tree, 2026-11-11 UTC, based on `0123456`" in head, kind


@pytest.mark.req("R-16.8-3")
def test_of_two_load_runs_only_the_newest_appears_and_nothing_is_summed(root: Path) -> None:
    older = {**LOAD_SUMMARY, "quotes_stored": 177, "evidence_lines": 1477}
    store(root, result("load", "20261110T090000Z", older))
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY))

    text = block_of(evidence.render(DOCUMENT, root), "load")

    assert "20261111T120000Z" in text
    assert "20261110T090000Z" not in text
    assert "| Quotes stored | 200 |" in text
    assert "| Evidence lines | 1600 |" in text
    assert "177" not in text
    assert "1477" not in text
    assert "377" not in text  # 200 + 177
    assert "3077" not in text  # 1600 + 1477


def test_a_failed_newest_run_renders_as_failed_with_its_findings(root: Path) -> None:
    store(root, result("load", "20261110T090000Z", LOAD_SUMMARY))
    failed = {**LOAD_SUMMARY, "findings": ["duplicate_quote_for_key: key 3: ['a', 'b']"]}
    store(root, result("load", "20261111T120000Z", failed, status="fail"))

    text = block_of(evidence.render(DOCUMENT, root), "load")

    assert text.startswith("**FAIL** · run `20261111T120000Z`")
    assert "Oracle findings: 1." in text
    assert "- `duplicate_quote_for_key: key 3: ['a', 'b']`" in text


def test_a_dirty_tree_prints_as_working_tree_with_the_date_and_the_base_commit() -> None:
    dirty = result("load", "r", {}, identity={"commit": COMMIT, "dirty": True})
    unknown = result("load", "r", {}, identity={"commit": None, "dirty": True})

    assert evidence.identity_text(result("load", "r", {})) == "`0123456`"
    assert evidence.identity_text(dirty) == "working tree, 2026-11-11 UTC, based on `0123456`"
    assert evidence.identity_text(unknown) == "working tree, 2026-11-11 UTC"


def test_the_evaluation_block_renders_what_the_summary_holds(root: Path) -> None:
    summary = {
        "model": "model-under-test",
        "prompt_version": "v1",
        "cases": 18,
        "epochs": 3,
        "pass_rate": "0.944",
        "scorers": {"tools_called": "1.000", "numbers_grounded": "0.944"},
    }
    store(root, result("evals", "20261111T120000Z", summary))

    text = block_of(evidence.render(DOCUMENT, root), "evals")

    assert "| Overall pass rate | 0.944 |" in text
    assert "| numbers_grounded | 0.944 |" in text


def test_a_mutation_run_is_converted_and_rendered_with_one_row_per_mutant(
    root: Path, document: Path
) -> None:
    raw_run(
        root,
        "mutation",
        "20261111T120000Z",
        {
            "passed": False,
            "catalogue_size": 2,
            "minimum_catalogue_size": 15,
            "tests": "tests/unit/pricing",
            "killed": 1,
            "survived": 1,
            "stale": 0,
            "errors": 0,
            "mutants": [
                {
                    "name": "payout_upper_clamp_removed",
                    "rule": "5.3 capped at the limit",
                    "file": "payout.py",
                    "result": "killed",
                    "first_failing_test": "tests/unit/pricing/test_payout.py::test_cap",
                    "seconds": 2.1,
                },
                {
                    "name": "rounding_half_up",
                    "rule": "5.5 half to even | once",
                    "file": "rounding.py",
                    "result": "survived",
                    "first_failing_test": None,
                    "seconds": 2.0,
                },
            ],
        },
    )

    two_hours_later = datetime(2026, 11, 11, 14, 0, tzinfo=UTC)
    assert evidence.command_render(root, document, now=two_hours_later) == 0

    stored = json.loads((root / "mutation/20261111T120000Z/result.json").read_text())
    assert stored["status"] == "fail"
    assert stored["measured_at"] == "2026-11-11T12:00:00+00:00"
    assert set(stored["identity"]) == {"commit", "dirty"}
    text = block_of(document.read_text(encoding="utf-8"), "mutation")
    assert text.startswith("**FAIL** · run `20261111T120000Z`")
    assert "2 mutants (minimum 15)" in text
    assert "1 killed, 1 survived" in text
    assert (
        "| rounding_half_up | 5.5 half to even \\| once | rounding.py | survived | none |" in text
    )
    # Converted long after the run: the document says so.
    assert "minutes after the run" in text


def test_a_failure_run_is_grouped_by_the_scenarios_of_the_specification(
    root: Path, document: Path
) -> None:
    raw_run(
        root,
        "failure",
        "20261111T120000Z",
        {
            "tests": [
                {"id": "t::carrier_503", "req": ["R-16.3-3", "R-7-5"], "outcome": "passed"},
                {"id": "t::duplicate_a", "req": ["R-16.3-4"], "outcome": "passed"},
                {"id": "t::duplicate_b", "req": ["R-16.3-4"], "outcome": "failed"},
            ]
        },
    )

    evidence.command_render(root, document)

    stored = json.loads((root / "failure/20261111T120000Z/result.json").read_text())
    scenarios = {s["id"]: s for s in stored["summary"]["scenarios"]}
    assert stored["status"] == "fail"
    assert len(scenarios) == 9  # SPEC 16.3 names nine scenarios
    assert (scenarios["R-16.3-3"]["tests"], scenarios["R-16.3-3"]["passed"]) == (1, 1)
    assert (scenarios["R-16.3-4"]["passed"], scenarios["R-16.3-4"]["failed"]) == (1, 1)
    assert scenarios["R-16.3-1"]["tests"] == 0  # a scenario without a test is shown, not hidden
    text = block_of(document.read_text(encoding="utf-8"), "failure")
    assert "3 tests: 2 passed, 1 failed." in text
    assert "| R-16.3-1 |" in text


def test_a_failure_run_with_an_untested_scenario_is_not_a_pass(root: Path, document: Path) -> None:
    raw_run(
        root,
        "failure",
        "20261111T120000Z",
        {"tests": [{"id": "t::only", "req": ["R-16.3-3"], "outcome": "passed"}]},
    )

    evidence.command_render(root, document)

    stored = json.loads((root / "failure/20261111T120000Z/result.json").read_text())
    assert stored["status"] == "fail"


def test_a_traceability_run_lists_the_requirements_it_did_not_prove(
    root: Path, document: Path
) -> None:
    raw_run(
        root,
        "traceability",
        "20261111T120000Z",
        {
            "summary": {"requirements": 3, "passed": 2, "failed": 0, "no_passing_test": 1},
            "requirements": [
                {
                    "id": "R-1-1",
                    "section": "1",
                    "text": "a",
                    "plan": "01",
                    "outcome": "passed",
                    "tests": [],
                },
                {
                    "id": "R-1-2",
                    "section": "1",
                    "text": "b",
                    "plan": "01",
                    "outcome": "passed",
                    "tests": [],
                },
                {
                    "id": "R-17-1",
                    "section": "17",
                    "text": "Deployed on Cloud Run.",
                    "plan": "09",
                    "outcome": "no passing test",
                    "tests": [],
                },
            ],
        },
    )

    evidence.command_render(root, document)

    text = block_of(document.read_text(encoding="utf-8"), "traceability")
    assert text.startswith("**PASS**")
    assert "3 requirements: 2 with a passing test, 0 with a failing test, 1 with no passing" in text
    assert "| R-17-1 | 17 | Deployed on Cloud Run. | no passing test |" in text
    assert "R-1-1" not in text


def test_check_passes_on_a_fresh_render_and_fails_on_an_edit_inside_a_block(
    root: Path, document: Path
) -> None:
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY))
    evidence.command_render(root, document)

    assert evidence.command_check(root, document, ["load"], COMMIT) == 0

    rendered = document.read_text(encoding="utf-8")
    document.write_text(rendered.replace("Written by hand, after.", "Edited by hand."), "utf-8")
    assert evidence.command_check(root, document, ["load"], COMMIT) == 0  # outside a block

    document.write_text(
        rendered.replace("| Quotes stored | 200 |", "| Quotes stored | 201 |"), "utf-8"
    )
    assert evidence.command_check(root, document, ["load"], COMMIT) == 1  # inside a block


def test_check_fails_when_a_required_kind_has_no_result_or_its_newest_failed(
    root: Path, document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store(root, result("load", "20261110T090000Z", LOAD_SUMMARY))
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY, status="fail"))
    evidence.command_render(root, document)

    assert evidence.command_check(root, document, [], COMMIT) == 0
    assert evidence.command_check(root, document, ["load"], COMMIT) == 1
    assert evidence.command_check(root, document, ["evals"], COMMIT) == 1
    errors = capsys.readouterr().err
    assert "load: the newest run 20261111T120000Z failed" in errors
    assert "evals: no result" in errors


def test_check_fails_while_a_finished_run_is_not_in_the_document(
    root: Path, document: Path
) -> None:
    evidence.command_render(root, document)
    raw_run(
        root,
        "failure",
        "20261111T130000Z",
        {"tests": [{"id": "t::only", "req": ["R-16.3-3"], "outcome": "passed"}]},
    )

    assert evidence.command_check(root, document, [], COMMIT) == 1
    assert not (root / "failure/20261111T130000Z/result.json").exists()  # check writes nothing


def test_check_names_a_section_that_was_not_measured_on_head(
    root: Path, document: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store(root, result("load", "20261111T120000Z", LOAD_SUMMARY))
    evidence.command_render(root, document)
    capsys.readouterr()

    evidence.command_check(root, document, ["load"], COMMIT)
    assert "note" not in capsys.readouterr().out

    evidence.command_check(root, document, ["load"], "f" * 40)
    assert "note: load was measured on `0123456`, not on HEAD" in capsys.readouterr().out


def test_render_refuses_a_document_without_a_block(root: Path, tmp_path: Path) -> None:
    path = tmp_path / "incomplete.md"
    path.write_text(DOCUMENT.replace("<!-- evidence:evals:begin -->", ""), encoding="utf-8")

    assert evidence.command_render(root, path) == 1
    assert "stale text" in path.read_text(encoding="utf-8")  # nothing was written
