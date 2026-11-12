"""The load requirements of SPEC 16.5 are proven by a campaign, not by this file.

`make load` runs the campaign and writes `.evidence/load/<run_id>/result.json`. This test
reads the newest result and fails when there is none or when it is a failure, so the
traceability matrix never shows the requirements as proven without a passing campaign. It
does not start anything: run `make load` first.
"""

import json
from pathlib import Path
from typing import Any

import pytest

# `evidence`: reads a stored campaign result and fails until that campaign has passed. The
# marker keeps this test out of `make test` and `make test-integration`; the traceability
# run includes it.
pytestmark = pytest.mark.evidence

EVIDENCE = Path(__file__).resolve().parents[4] / ".evidence" / "load"


def newest_result() -> dict[str, Any]:
    results = sorted(EVIDENCE.glob("*/result.json"))  # run ids are UTC timestamps: they sort
    if not results:
        pytest.fail(f"no load result under {EVIDENCE}: run `make load`")
    result: dict[str, Any] = json.loads(results[-1].read_text(encoding="utf-8"))
    return result


@pytest.mark.req("R-16.5-1", "R-16.5-2", "R-16.5-3")
def test_the_newest_load_campaign_passed_under_the_declared_profile() -> None:
    result = newest_result()
    summary = result["summary"]

    assert result["kind"] == "load"
    assert result["status"] == "pass", summary["findings"]
    assert summary["findings"] == []
    # The campaign that passed is the declared one, on the local stack.
    assert summary["target"] == "http://api:8080"
    assert summary["evidence_lines"] == summary["scheduled_requests"] == 1600
    assert summary["quotes_stored"] <= summary["distinct_keys"] == 200
    assert summary["keys_acknowledged"] >= 1
    assert summary["cells_requests_answered"] == 600
    thresholds = summary["profile"]["thresholds"]
    assert thresholds["http_req_duration{scenario:quotes}"] == ["p(95)<2000"]
    assert thresholds["http_req_duration{scenario:cells}"] == ["p(95)<1000"]
    for metric, expressions in thresholds.items():
        for expression in expressions:
            assert summary["thresholds"][metric][expression] == {"ok": True}
