"""The mutation proof script judges itself: a harmless mutant survives, a stale one is named.

Slow (each run executes the pricing unit tests twice) and outside `tests/unit/pricing`, so
these tests never run inside a mutation run.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3]
SCRIPT = BACKEND / "scripts" / "mutation_proof.py"
PAYOUT = BACKEND / "src" / "veranico" / "modules" / "pricing" / "domain" / "payout.py"

CATALOGUE_TEMPLATE = '''"""A one-entry catalogue for the script's own tests."""

from typing import NamedTuple


class Mutant(NamedTuple):
    name: str
    file: str
    find: str
    replace: str
    rule: str


CATALOGUE = (Mutant({name!r}, "payout.py", {find!r}, {replace!r}, "none"),)
'''


def run_script(
    tmp_path: Path, name: str, find: str, replace: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    catalogue = tmp_path / "catalogue.py"
    catalogue.write_text(
        CATALOGUE_TEMPLATE.format(name=name, find=find, replace=replace), encoding="utf-8"
    )
    result_file = tmp_path / "result" / "mutants.json"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--catalogue", str(catalogue), "--json", str(result_file)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return done, json.loads(result_file.read_text(encoding="utf-8"))


@pytest.mark.slow
@pytest.mark.req("R-16.4-1")
def test_mutant_that_only_changes_a_comment_survives_and_fails_the_run(tmp_path: Path) -> None:
    before = PAYOUT.read_text(encoding="utf-8")
    comment = "The payout is the limit times the fraction."  # a docstring line of payout.py
    assert before.count(comment) == 1

    done, result = run_script(tmp_path, "harmless", comment, "The payout is described here.")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "SURVIVED" in done.stdout
    assert result["passed"] is False
    assert result["survived"] == 1
    assert result["mutants"] == [
        {
            "name": "harmless",
            "rule": "none",
            "file": "payout.py",
            "result": "SURVIVED",
            "first_failing_test": None,
            "seconds": pytest.approx(0, abs=600),
        }
    ]
    assert PAYOUT.read_text(encoding="utf-8") == before  # the working tree is untouched


@pytest.mark.slow
@pytest.mark.req("R-16.4-1")
def test_mutant_whose_text_is_absent_is_reported_stale_and_fails_the_run(tmp_path: Path) -> None:
    done, result = run_script(tmp_path, "gone", "this text is not in payout.py", "anything")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "stale" in done.stdout
    assert result["passed"] is False
    assert result["stale"] == 1
    assert result["killed"] == 0


@pytest.mark.slow
@pytest.mark.req("R-16.4-1")
def test_real_mutant_is_killed_but_a_catalogue_under_fifteen_still_fails(tmp_path: Path) -> None:
    done, result = run_script(
        tmp_path, "no_cap", "return np.minimum(floored, 1.0)", "return floored"
    )

    assert done.returncode == 1, done.stdout + done.stderr  # one mutant is not a catalogue
    assert result["killed"] == 1
    assert result["catalogue_size"] == 1
    assert "at least 15" in done.stdout
    mutants = result["mutants"]
    assert isinstance(mutants, list)
    assert mutants[0]["result"] == "killed"
    assert mutants[0]["first_failing_test"].startswith("tests/unit/pricing/")
