"""The oracle of the load campaign (SPEC 16.5): what the run directory proves.

`verify(run_dir)` is a pure function over the files of one run and returns the findings; an
empty list is a pass. It reads nothing else: no service, no emulator, no clock.

    fixtures.json     the schedule k6 was given (load/fixtures.py)
    responses.jsonl   one evidence line per request, written by k6
    k6-summary.json   the end-of-test summary of k6, thresholds included
    firestore.json    what the emulator held after the run: document ids and the key to
                      quote mapping only (load/run.py writes it)

What it asserts:

(a) one well-formed evidence line per scheduled request: none missing, none twice, none
    that was not scheduled, and no status other than success or back-pressure;
(b) all acknowledged responses of one idempotency key carry the same `quote_id`;
(c) every acknowledged `quote_id` exists in `quoting_quotes`, in the workspace of the run;
(d) at most one quote per key, exactly the recorded one for a key that has a durable
    record, and no quote without a key of the run;
(e) the thresholds in the k6 summary are the ones the profile declares, and all hold.

A key that was never acknowledged (every send refused as back-pressure) may have no quote;
it may never have two.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROFILE = Path(__file__).resolve().parent / "profile.json"

ACKNOWLEDGED = 200
BACK_PRESSURE = 429
SCENARIOS = ("quotes", "cells")
_LINE_KEYS = {"scenario", "index", "key_index", "status", "quote_id"}


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class Run:
    fixtures: dict[str, Any]
    lines: list[Any]  # each evidence line parsed, or the raw text when it is not JSON
    summary: dict[str, Any]
    firestore: dict[str, Any]
    profile: dict[str, Any]


def load(run_dir: Path, profile: Path = PROFILE) -> Run:
    def read(name: str) -> Any:
        return json.loads((run_dir / name).read_text(encoding="utf-8"))

    lines: list[Any] = []
    for raw in (run_dir / "responses.jsonl").read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            lines.append(raw)
    return Run(
        fixtures=read("fixtures.json"),
        lines=lines,
        summary=read("k6-summary.json"),
        firestore=read("firestore.json"),
        profile=json.loads(profile.read_text(encoding="utf-8")),
    )


def verify(run_dir: Path, profile: Path = PROFILE) -> list[Finding]:
    run = load(run_dir, profile)
    evidence, findings = _evidence(run)
    acknowledged = _acknowledged(evidence)
    findings += _one_quote_id_per_key(acknowledged)
    findings += _stored(run, acknowledged)
    findings += _thresholds(run)
    return findings


def summarise(run_dir: Path, profile: Path = PROFILE) -> dict[str, Any]:
    """Counts and measured latencies of a run, for `result.json`. Judges nothing."""
    run = load(run_dir, profile)
    evidence, _ = _evidence(run)
    statuses = Counter(
        (line["scenario"], line["status"]) for line in evidence if isinstance(line["status"], int)
    )
    acknowledged = _acknowledged(evidence)
    metrics = run.summary.get("metrics", {})
    return {
        "scheduled_requests": len(run.fixtures["quotes"]) + len(run.fixtures["cells"]),
        "evidence_lines": len(run.lines),
        "distinct_keys": len({entry["key"] for entry in run.fixtures["quotes"]}),
        "quote_sends": len(run.fixtures["quotes"]),
        "quote_sends_acknowledged": statuses[("quotes", ACKNOWLEDGED)],
        "quote_sends_refused_as_back_pressure": statuses[("quotes", BACK_PRESSURE)],
        "keys_acknowledged": len(acknowledged),
        "quotes_stored": len(run.firestore["quotes"]),
        "idempotency_records": len(run.firestore["idempotency"]),
        "cells_requests": len(run.fixtures["cells"]),
        "cells_requests_answered": statuses[("cells", ACKNOWLEDGED)],
        "latency_ms": {
            scenario: metrics.get(f"http_req_duration{{scenario:{scenario}}}", {}).get("values")
            for scenario in SCENARIOS
        },
        "thresholds": {
            metric: {
                expression: metrics.get(metric, {}).get("thresholds", {}).get(expression)
                for expression in expressions
            }
            for metric, expressions in run.profile["thresholds"].items()
        },
    }


def _evidence(run: Run) -> tuple[list[dict[str, Any]], list[Finding]]:
    """(a) The well-formed lines, and what is wrong with the evidence as a whole."""
    findings: list[Finding] = []
    scheduled: dict[tuple[str, int], int | None] = {}
    for entry in run.fixtures["quotes"]:
        scheduled[("quotes", entry["index"])] = entry["key_index"]
    for entry in run.fixtures["cells"]:
        scheduled[("cells", entry["index"])] = None

    good: list[dict[str, Any]] = []
    seen: Counter[tuple[str, int]] = Counter()
    for number, line in enumerate(run.lines, start=1):
        if not _well_formed(line):
            findings.append(Finding("evidence_malformed", f"line {number} is not an evidence line"))
            continue
        request = (line["scenario"], line["index"])
        if request not in scheduled:
            findings.append(Finding("evidence_unscheduled", f"{request} was never scheduled"))
            continue
        if line["key_index"] != scheduled[request]:
            findings.append(Finding("evidence_malformed", f"{request} names another key"))
            continue
        seen[request] += 1
        if seen[request] > 1:
            findings.append(Finding("evidence_duplicate", f"{request} appears more than once"))
            continue
        good.append(line)
        expected = (
            (ACKNOWLEDGED, BACK_PRESSURE) if line["scenario"] == "quotes" else (ACKNOWLEDGED,)
        )
        if line["status"] not in expected:
            findings.append(
                Finding("unexpected_status", f"{request} was answered {line['status']}")
            )
        elif request[0] == "quotes" and line["status"] == ACKNOWLEDGED and not line["quote_id"]:
            findings.append(Finding("unexpected_status", f"{request} acknowledged no quote_id"))
    missing = sorted(request for request in scheduled if request not in seen)
    findings += [
        Finding("evidence_missing", f"{request} has no evidence line") for request in missing
    ]
    return good, findings


def _well_formed(line: object) -> bool:
    return (
        isinstance(line, dict)
        and set(line) == _LINE_KEYS
        and line["scenario"] in SCENARIOS
        and type(line["index"]) is int
        and type(line["status"]) is int
        and (line["key_index"] is None or type(line["key_index"]) is int)
        and (line["quote_id"] is None or isinstance(line["quote_id"], str))
    )


def _acknowledged(evidence: list[dict[str, Any]]) -> dict[int, set[str]]:
    """The quote ids acknowledged per key index."""
    acknowledged: dict[int, set[str]] = {}
    for line in evidence:
        if line["scenario"] == "quotes" and line["status"] == ACKNOWLEDGED and line["quote_id"]:
            acknowledged.setdefault(line["key_index"], set()).add(line["quote_id"])
    return acknowledged


def _one_quote_id_per_key(acknowledged: dict[int, set[str]]) -> list[Finding]:
    """(b)"""
    return [
        Finding("key_acknowledged_with_different_quotes", f"key {key_index}: {sorted(quote_ids)}")
        for key_index, quote_ids in sorted(acknowledged.items())
        if len(quote_ids) > 1
    ]


def _stored(run: Run, acknowledged: dict[int, set[str]]) -> list[Finding]:
    """(c) and (d), against the snapshot of the emulator."""
    findings: list[Finding] = []
    workspace = run.firestore["workspace_id"]
    key_of_ref = {
        ref: entry["key_index"]
        for entry in run.fixtures["quotes"]
        if (ref := run.firestore["key_refs"].get(entry["key"])) is not None
    }
    if len(key_of_ref) != len({entry["key"] for entry in run.fixtures["quotes"]}):
        findings.append(Finding("snapshot_incomplete", "a scheduled key has no reference"))

    quotes_of_key: dict[int, list[str]] = {}
    in_workspace: set[str] = set()
    for quote in run.firestore["quotes"]:
        quote_id = quote["quote_id"]
        if quote["workspace_id"] != workspace:
            findings.append(Finding("quote_without_key", f"{quote_id} is in another workspace"))
            continue
        in_workspace.add(quote_id)
        key_index = key_of_ref.get(quote["idempotency_ref"])
        if key_index is None:
            findings.append(
                Finding("quote_without_key", f"{quote_id} belongs to no key of the run")
            )
            continue
        quotes_of_key.setdefault(key_index, []).append(quote_id)

    for key_index, quote_ids in sorted(acknowledged.items()):
        for quote_id in sorted(quote_ids - in_workspace):
            findings.append(
                Finding("acknowledged_quote_missing", f"key {key_index}: {quote_id} is not stored")
            )
    for key_index, stored in sorted(quotes_of_key.items()):
        if len(stored) > 1:
            findings.append(
                Finding("duplicate_quote_for_key", f"key {key_index}: {sorted(stored)}")
            )

    recorded: dict[int, str] = {}
    for record in run.firestore["idempotency"]:
        key_index = key_of_ref.get(record["ref"])
        if key_index is None or record["workspace_id"] != workspace:
            findings.append(Finding("record_without_key", f"{record['ref']} is no key of the run"))
            continue
        recorded[key_index] = record["quote_id"]
    for key_index, quote_id in sorted(recorded.items()):
        stored = quotes_of_key.get(key_index, [])
        # Two quotes for the key are already reported above as a duplicate.
        if len(stored) < 2 and stored != [quote_id]:
            findings.append(
                Finding("recorded_quote_missing", f"key {key_index}: the record names {quote_id}")
            )
    for key_index, quote_ids in sorted(acknowledged.items()):
        if len(quote_ids) == 1 and recorded.get(key_index) not in quote_ids:
            findings.append(
                Finding("acknowledged_quote_not_recorded", f"key {key_index}: {sorted(quote_ids)}")
            )
    return findings


def _thresholds(run: Run) -> list[Finding]:
    """(e) The summary holds exactly the declared thresholds, and each one held."""
    findings: list[Finding] = []
    declared: dict[str, list[str]] = run.profile["thresholds"]
    metrics: dict[str, Any] = run.summary.get("metrics", {})
    for metric, values in sorted(metrics.items()):
        measured = set(values.get("thresholds", {}))
        if measured != set(declared.get(metric, [])):
            findings.append(
                Finding(
                    "threshold_not_declared",
                    f"{metric}: the run used {sorted(measured)}, "
                    f"the profile declares {sorted(declared.get(metric, []))}",
                )
            )
    for metric, expressions in sorted(declared.items()):
        outcomes = metrics.get(metric, {}).get("thresholds")
        if outcomes is None:
            if metric not in metrics:
                findings.append(
                    Finding("threshold_not_declared", f"{metric}: not in the summary of the run")
                )
            continue
        for expression in expressions:
            if expression in outcomes and outcomes[expression].get("ok") is not True:
                findings.append(Finding("threshold_failed", f"{metric}: {expression} did not hold"))
    return findings
