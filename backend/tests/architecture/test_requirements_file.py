"""`tests/requirements.yaml` is well formed, and `scripts/traceability.py` reads it."""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]
REQUIREMENTS = BACKEND / "tests" / "requirements.yaml"
SPEC = BACKEND.parent / "docs" / "SPEC.md"
SCRIPT = BACKEND / "scripts" / "traceability.py"
IDENTIFIER = re.compile(r"\AR-(\d+(?:\.\d+)?)-([1-9]\d*)\Z")

# Sections 2 to 17 with at least one normative statement, plus the disclaimer of section 1.
# 16.1 lists tests of requirements stated elsewhere; 10, 12 and 16 are covered by their parts
# where they have no statement of their own.
SECTIONS_WITH_ENTRIES = {
    *("1", "2", "3", "3.1", "3.2"),
    *("4", "4.1", "4.2", "4.3", "4.4"),
    *("5", "5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8"),
    *("6", "7", "8"),
    *("9.1", "9.2", "9.3", "9.4", "9.5", "9.6"),
    *("10", "10.1", "10.2", "10.3"),
    *("11", "11.1", "11.2", "11.3", "11.4"),
    *("12", "12.1", "12.2", "12.3", "12.4", "12.5", "12.6"),
    *("13", "14", "15"),
    *("16.2", "16.3", "16.4", "16.5", "16.6", "16.7", "16.8", "16.9"),
    "17",
}


def entries() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(REQUIREMENTS.read_text(encoding="utf-8"))
    assert isinstance(loaded["requirements"], list)
    return list(loaded["requirements"])


def spec_sections() -> set[str]:
    headings = re.findall(r"^#{2,3} (\d+(?:\.\d+)?)[. ]", SPEC.read_text(encoding="utf-8"), re.M)
    return set(headings)


def test_identifiers_are_unique_and_match_the_pattern() -> None:
    identifiers = [entry["id"] for entry in entries()]

    assert [i for i, count in Counter(identifiers).items() if count > 1] == []
    assert [i for i in identifiers if not IDENTIFIER.match(i)] == []


def test_every_entry_has_exactly_the_four_fields_as_non_empty_strings() -> None:
    for entry in entries():
        assert set(entry) == {"id", "section", "text", "plan"}, entry
        assert all(isinstance(value, str) and value.strip() for value in entry.values()), entry


def test_the_section_of_an_entry_is_the_one_in_its_identifier() -> None:
    for entry in entries():
        match = IDENTIFIER.match(entry["id"])
        assert match is not None
        assert entry["section"] == match[1], entry["id"]


@pytest.mark.req("R-16.8-1")
def test_every_section_exists_in_the_spec() -> None:
    sections = spec_sections()

    assert {"1", "3.1", "16.9", "17"} <= sections  # the headings were parsed
    assert {entry["section"] for entry in entries()} - sections == set()


def test_the_sections_with_requirements_are_the_expected_ones() -> None:
    assert {entry["section"] for entry in entries()} == SECTIONS_WITH_ENTRIES


def test_numbers_inside_a_section_are_contiguous_from_one() -> None:
    by_section: dict[str, list[int]] = {}
    for entry in entries():
        match = IDENTIFIER.match(entry["id"])
        assert match is not None
        by_section.setdefault(match[1], []).append(int(match[2]))

    for section, numbers in by_section.items():
        assert sorted(numbers) == list(range(1, len(numbers) + 1)), section


def test_a_text_is_one_statement_on_one_line() -> None:
    for entry in entries():
        assert "\n" not in entry["text"], entry["id"]
        assert len(entry["text"]) >= 10, entry["id"]


def test_plans_are_two_digit_plan_numbers() -> None:
    for entry in entries():
        numbers = re.findall(r"\b\d{2}\b", entry["plan"])
        assert numbers, entry["id"]
        assert all(0 <= int(number) <= 10 for number in numbers), entry["id"]


# scripts/traceability.py


def run(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)]
    return subprocess.run(command, capture_output=True, text=True, cwd=BACKEND, check=False)


@pytest.fixture
def small(tmp_path: Path) -> Path:
    """Three requirements and two reports: one proven, one failing, one without a test."""
    requirements = [
        {"id": "R-1-1", "section": "1", "text": "First statement.", "plan": "00"},
        {"id": "R-1-2", "section": "1", "text": "Second statement.", "plan": "00"},
        {"id": "R-2-1", "section": "2", "text": "Third statement.", "plan": "01"},
    ]
    (tmp_path / "requirements.yaml").write_text(yaml.safe_dump({"requirements": requirements}))
    backend = [
        {"id": "tests/a.py::test_one", "req": ["R-1-1"], "outcome": "passed"},
        {"id": "tests/a.py::test_two", "req": ["R-1-1", "R-1-2"], "outcome": "passed"},
        {"id": "tests/a.py::test_unmarked", "req": [], "outcome": "passed"},
        {"id": "tests/a.py::test_skipped", "req": ["R-2-1"], "outcome": "skipped"},
    ]
    frontend = [{"id": "src/a.test.ts > [R-1-2] renders", "req": ["R-1-2"], "outcome": "failed"}]
    (tmp_path / "backend.json").write_text(json.dumps({"tests": backend}))
    (tmp_path / "frontend.json").write_text(json.dumps({"tests": frontend}))
    return tmp_path


def reports(directory: Path) -> list[str | Path]:
    return [
        "--requirements",
        directory / "requirements.yaml",
        "--report",
        directory / "backend.json",
        "--report",
        directory / "frontend.json",
    ]


@pytest.mark.req("R-16.8-1")
def test_check_ids_passes_when_every_marker_names_a_known_requirement(small: Path) -> None:
    result = run("--check-ids", *reports(small))

    assert result.returncode == 0, result.stderr


@pytest.mark.req("R-16.8-1")
def test_check_ids_fails_on_a_marker_that_is_not_in_the_file(small: Path) -> None:
    unknown = [{"id": "tests/b.py::test_typo", "req": ["R-9-99"], "outcome": "passed"}]
    (small / "frontend.json").write_text(json.dumps({"tests": unknown}))

    result = run("--check-ids", *reports(small))

    assert result.returncode == 1
    assert "R-9-99" in result.stderr
    assert "tests/b.py::test_typo" in result.stderr


@pytest.mark.req("R-16.8-1")
def test_matrix_prints_requirement_tests_and_outcome_as_markdown(small: Path) -> None:
    result = run("--matrix", *reports(small))

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "| Requirement | Statement | Tests | Outcome |"
    assert lines[1] == "|---|---|---|---|"
    rows = {line.split(" | ")[0].strip("| "): line for line in lines[2:5]}
    assert rows["R-1-1"].endswith("| passed |")
    assert "`tests/a.py::test_one`<br>`tests/a.py::test_two`" in rows["R-1-1"]
    assert rows["R-1-2"].endswith("| failed |")  # one passing test and one failing one
    assert rows["R-2-1"].endswith("| no passing test |")
    assert "test_unmarked" not in result.stdout


@pytest.mark.req("R-16.8-1")
def test_json_output_lists_requirement_tests_and_outcome(small: Path) -> None:
    result = run("--json", small / "matrix.json", *reports(small))

    assert result.returncode == 0, result.stderr
    matrix = json.loads((small / "matrix.json").read_text())
    assert [row["id"] for row in matrix["requirements"]] == ["R-1-1", "R-1-2", "R-2-1"]
    assert matrix["requirements"][0] == {
        "id": "R-1-1",
        "section": "1",
        "text": "First statement.",
        "plan": "00",
        "outcome": "passed",
        "tests": [
            {"id": "tests/a.py::test_one", "outcome": "passed"},
            {"id": "tests/a.py::test_two", "outcome": "passed"},
        ],
    }
    assert matrix["summary"] == {"requirements": 3, "passed": 1, "failed": 1, "no_passing_test": 1}


@pytest.mark.req("R-16.8-1")
def test_require_all_fails_when_a_requirement_has_no_passing_test(small: Path) -> None:
    result = run("--require-all", *reports(small))

    assert result.returncode == 1
    assert "R-1-2" in result.stderr
    assert "R-2-1" in result.stderr
    assert "R-1-1" not in result.stderr


@pytest.mark.req("R-16.8-1")
def test_require_all_passes_when_every_requirement_is_proven(small: Path) -> None:
    proven = [{"id": "t::all", "req": ["R-1-1", "R-1-2", "R-2-1"], "outcome": "passed"}]
    (small / "backend.json").write_text(json.dumps({"tests": proven}))
    (small / "frontend.json").write_text(json.dumps({"tests": []}))

    result = run("--require-all", "--check-ids", *reports(small))

    assert result.returncode == 0, result.stderr


def test_a_report_in_another_shape_or_a_missing_report_is_an_error(small: Path) -> None:
    (small / "frontend.json").write_text(json.dumps({"results": []}))

    malformed = run("--check-ids", *reports(small))
    missing = run("--check-ids", "--requirements", small / "requirements.yaml")
    absent = run(
        "--check-ids",
        "--requirements",
        small / "requirements.yaml",
        "--report",
        small / "nothing.json",
    )

    assert malformed.returncode == 2
    assert "frontend.json" in malformed.stderr
    assert missing.returncode == 2
    assert absent.returncode == 2


def test_the_real_file_is_read_by_the_script(tmp_path: Path) -> None:
    (tmp_path / "empty.json").write_text(json.dumps({"tests": []}))

    listed = run("--check-ids", "--matrix", "--report", tmp_path / "empty.json")
    required = run("--require-all", "--report", tmp_path / "empty.json")

    assert listed.returncode == 0, listed.stderr
    assert len(listed.stdout.splitlines()) == len(entries()) + 2
    assert required.returncode == 1  # nothing is proven by an empty report
