"""The oracle detects each defect it claims to detect (`load/oracle.py`).

    cd backend && uv run pytest ../load/tests -q

A passing run directory is built here, then one defect is planted at a time. Every planted
defect must be reported under its own code, and the clean directory alone must pass: an
oracle that reports nothing is not evidence unless it is shown to report something.
"""

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

LOAD = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-of-the-run"
RUN_ID = "run-under-test"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"load_{name}", LOAD / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


fixtures = _load("fixtures")
oracle = _load("oracle")
PROFILE: dict[str, Any] = json.loads((LOAD / "profile.json").read_text(encoding="utf-8"))

Files = dict[str, Any]


def _ref(key: str) -> str:
    return hashlib.sha256(f"{WORKSPACE}:{key}".encode()).hexdigest()


def passing_run() -> Files:
    """What a correct service leaves behind: every key acknowledged with its one quote."""
    schedule = fixtures.build(RUN_ID, PROFILE["seed"], PROFILE)
    keys = sorted({entry["key"] for entry in schedule["quotes"]})
    quote_of = {key: f"quote-{number:03d}" for number, key in enumerate(keys)}
    lines = [
        {
            "scenario": "quotes",
            "index": entry["index"],
            "key_index": entry["key_index"],
            "status": 200,
            "quote_id": quote_of[entry["key"]],
        }
        for entry in schedule["quotes"]
    ] + [
        {
            "scenario": "cells",
            "index": entry["index"],
            "key_index": None,
            "status": 200,
            "quote_id": None,
        }
        for entry in schedule["cells"]
    ]
    return {
        "fixtures": schedule,
        "lines": lines,
        "summary": {
            "metrics": {
                "http_req_duration": {"values": {"p(95)": 300.0}},
                **{
                    metric: {
                        "values": {"p(95)": 300.0},
                        "thresholds": {expression: {"ok": True} for expression in expressions},
                    }
                    for metric, expressions in PROFILE["thresholds"].items()
                },
            }
        },
        "firestore": {
            "workspace_id": WORKSPACE,
            "key_refs": {key: _ref(key) for key in keys},
            "quotes": [
                {"quote_id": quote_of[key], "workspace_id": WORKSPACE, "idempotency_ref": _ref(key)}
                for key in keys
            ],
            "idempotency": [
                {"ref": _ref(key), "workspace_id": WORKSPACE, "quote_id": quote_of[key]}
                for key in keys
            ],
        },
    }


def write(run_dir: Path, files: Files) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "fixtures.json").write_text(json.dumps(files["fixtures"]), encoding="utf-8")
    (run_dir / "k6-summary.json").write_text(json.dumps(files["summary"]), encoding="utf-8")
    (run_dir / "firestore.json").write_text(json.dumps(files["firestore"]), encoding="utf-8")
    lines = [line if isinstance(line, str) else json.dumps(line) for line in files["lines"]]
    (run_dir / "responses.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def codes(run_dir: Path) -> set[str]:
    return {finding.code for finding in oracle.verify(run_dir)}


def _key(files: Files, key_index: int) -> str:
    return str(next(e["key"] for e in files["fixtures"]["quotes"] if e["key_index"] == key_index))


def _lines_of_key(files: Files, key_index: int) -> list[dict[str, Any]]:
    return [
        line
        for line in files["lines"]
        if line["scenario"] == "quotes" and line["key_index"] == key_index
    ]


# One planted defect each. The name says what a broken service or a broken run did.


def two_quotes_for_one_key(files: Files) -> None:
    files["firestore"]["quotes"].append(
        {
            "quote_id": "quote-second",
            "workspace_id": WORKSPACE,
            "idempotency_ref": _ref(_key(files, 3)),
        }
    )


def an_acknowledged_quote_is_not_stored(files: Files) -> None:
    acknowledged = _lines_of_key(files, 5)[0]["quote_id"]
    files["firestore"]["quotes"] = [
        quote for quote in files["firestore"]["quotes"] if quote["quote_id"] != acknowledged
    ]


def an_acknowledged_quote_is_in_another_workspace(files: Files) -> None:
    acknowledged = _lines_of_key(files, 5)[0]["quote_id"]
    for quote in files["firestore"]["quotes"]:
        if quote["quote_id"] == acknowledged:
            quote["workspace_id"] = "another-workspace"


def two_ids_acknowledged_for_one_key(files: Files) -> None:
    _lines_of_key(files, 8)[1]["quote_id"] = "quote-other"


def a_quote_without_a_key(files: Files) -> None:
    files["firestore"]["quotes"].append(
        {"quote_id": "quote-orphan", "workspace_id": WORKSPACE, "idempotency_ref": "f" * 64}
    )


def a_quote_with_no_reference_at_all(files: Files) -> None:
    files["firestore"]["quotes"].append(
        {"quote_id": "quote-orphan", "workspace_id": WORKSPACE, "idempotency_ref": None}
    )


def an_evidence_line_is_missing(files: Files) -> None:
    files["lines"].pop(17)


def an_evidence_line_appears_twice(files: Files) -> None:
    files["lines"].append(dict(files["lines"][17]))


def an_evidence_line_is_not_json(files: Files) -> None:
    files["lines"][17] = "level=error msg=something else on the console"


def an_evidence_line_was_never_scheduled(files: Files) -> None:
    files["lines"].append(
        {"scenario": "cells", "index": 9999, "key_index": None, "status": 200, "quote_id": None}
    )


def a_request_was_answered_500(files: Files) -> None:
    line = _lines_of_key(files, 11)[2]
    line["status"], line["quote_id"] = 500, None


def a_latency_threshold_failed(files: Files) -> None:
    metric = "http_req_duration{scenario:quotes}"
    files["summary"]["metrics"][metric]["thresholds"]["p(95)<2000"]["ok"] = False


def the_run_used_a_looser_threshold_than_the_profile(files: Files) -> None:
    metric = "http_req_duration{scenario:quotes}"
    files["summary"]["metrics"][metric]["thresholds"] = {"p(95)<5000": {"ok": True}}


def the_run_dropped_a_declared_threshold(files: Files) -> None:
    del files["summary"]["metrics"]["http_req_duration{scenario:cells}"]


def the_record_of_a_key_names_another_quote(files: Files) -> None:
    files["firestore"]["idempotency"][4]["quote_id"] = "quote-elsewhere"


DEFECTS: dict[Callable[[Files], None], str] = {
    two_quotes_for_one_key: "duplicate_quote_for_key",
    an_acknowledged_quote_is_not_stored: "acknowledged_quote_missing",
    an_acknowledged_quote_is_in_another_workspace: "acknowledged_quote_missing",
    two_ids_acknowledged_for_one_key: "key_acknowledged_with_different_quotes",
    a_quote_without_a_key: "quote_without_key",
    a_quote_with_no_reference_at_all: "quote_without_key",
    an_evidence_line_is_missing: "evidence_missing",
    an_evidence_line_appears_twice: "evidence_duplicate",
    an_evidence_line_is_not_json: "evidence_malformed",
    an_evidence_line_was_never_scheduled: "evidence_unscheduled",
    a_request_was_answered_500: "unexpected_status",
    a_latency_threshold_failed: "threshold_failed",
    the_run_used_a_looser_threshold_than_the_profile: "threshold_not_declared",
    the_run_dropped_a_declared_threshold: "threshold_not_declared",
    the_record_of_a_key_names_another_quote: "recorded_quote_missing",
}


def test_the_clean_run_passes(tmp_path: Path) -> None:
    assert oracle.verify(write(tmp_path, passing_run())) == []


@pytest.mark.parametrize("defect", DEFECTS, ids=lambda defect: defect.__name__)
def test_each_planted_defect_is_reported(defect: Callable[[Files], None], tmp_path: Path) -> None:
    files = passing_run()
    defect(files)

    assert DEFECTS[defect] in codes(write(tmp_path, files))


def test_a_key_refused_every_time_may_have_no_quote_but_never_two(tmp_path: Path) -> None:
    files = passing_run()
    refused = _key(files, 7)
    for line in _lines_of_key(files, 7):
        line["status"], line["quote_id"] = 429, None
    stored = files["firestore"]
    stored["quotes"] = [q for q in stored["quotes"] if q["idempotency_ref"] != _ref(refused)]
    stored["idempotency"] = [r for r in stored["idempotency"] if r["ref"] != _ref(refused)]

    assert oracle.verify(write(tmp_path / "none", files)) == []

    for number in (1, 2):
        stored["quotes"].append(
            {
                "quote_id": f"late-{number}",
                "workspace_id": WORKSPACE,
                "idempotency_ref": _ref(refused),
            }
        )
    assert "duplicate_quote_for_key" in codes(write(tmp_path / "two", files))


def test_a_threshold_from_another_profile_is_reported(tmp_path: Path) -> None:
    stricter = json.loads(json.dumps(PROFILE))
    stricter["thresholds"]["http_req_duration{scenario:quotes}"] = ["p(95)<500"]
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(stricter), encoding="utf-8")
    run_dir = write(tmp_path / "run", passing_run())

    found = {finding.code for finding in oracle.verify(run_dir, profile)}

    assert found == {"threshold_not_declared"}


def test_the_summary_counts_what_the_files_hold(tmp_path: Path) -> None:
    files = passing_run()
    for line in _lines_of_key(files, 7)[:2]:
        line["status"], line["quote_id"] = 429, None

    summary = oracle.summarise(write(tmp_path, files))

    assert summary["scheduled_requests"] == 1600
    assert summary["evidence_lines"] == 1600
    assert (summary["distinct_keys"], summary["keys_acknowledged"]) == (200, 200)
    assert summary["quote_sends_acknowledged"] == 998
    assert summary["quote_sends_refused_as_back_pressure"] == 2
    assert (summary["quotes_stored"], summary["idempotency_records"]) == (200, 200)
    assert summary["cells_requests_answered"] == 600
    assert summary["latency_ms"]["quotes"] == {"p(95)": 300.0}
    assert summary["thresholds"]["checks"] == {"rate==1": {"ok": True}}
