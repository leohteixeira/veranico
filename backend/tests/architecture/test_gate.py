"""`scripts/gate.py`: the step lists, the three states and the exit codes of a gate."""

import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "gate.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("veranico_gate_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


gate = _load()


def _exits(code: int) -> str:
    return f'"{sys.executable}" -c "import sys; sys.exit({code})"'


def _run(*steps: object) -> tuple[int, str]:
    out = io.StringIO()
    return gate.run_gate("m0", list(steps), out), out.getvalue()


def _rows(text: str) -> list[tuple[str, str, str]]:
    """Number, step name and state of each row of the summary table."""
    cells = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in text.splitlines()
        if re.match(r"\| \d+ \|", line)
    ]
    return [(row[0], row[1], row[2]) for row in cells]


def test_m0_runs_exactly_the_ten_steps_of_the_delivery_contract() -> None:
    assert [step.name for step in gate.GATES["m0"].steps] == [
        "lint",
        "architecture tests",
        "fakes satisfy their Protocols",
        "routes of SPEC 11 in OpenAPI with contract schemas",
        "client drift",
        "frontend type check and build",
        "Compose file",
        "emulator smoke test",
        "/healthz on both roles",
        "gitleaks",
    ]
    assert not any(step.may_be_open for step in gate.GATES["m0"].steps)


def test_every_gate_of_the_delivery_contract_exists() -> None:
    assert list(gate.GATES) == ["m0", "m1", "m2", "m3", "m4", "m5", "m6"]


def test_every_gitleaks_call_redacts() -> None:
    for definition in gate.GATES.values():
        for step in definition.steps:
            for part in step.command.split("&&"):
                if "gitleaks" in part:
                    assert "--redact" in part, step.name


def test_a_step_that_may_be_open_does_not_go_through_make() -> None:
    """GNU Make exits 2 for any failed recipe, which would hide the exit code 3 of the script."""
    for definition in gate.GATES.values():
        for step in definition.steps:
            if step.may_be_open:
                assert not step.command.lstrip().startswith("make"), step.name


def test_no_step_prints_a_resolved_compose_file() -> None:
    """`docker compose config` without `-q` prints interpolated values."""
    for definition in gate.GATES.values():
        for step in definition.steps:
            for part in step.command.split("&&"):
                if "compose" in part and " config" in part:
                    assert " -q" in part, step.name


def test_all_passed_exits_zero_with_one_row_per_step() -> None:
    code, text = _run(
        gate.Step("first", _exits(0), BACKEND), gate.Step("second", _exits(0), BACKEND)
    )

    assert code == 0
    assert len(_rows(text)) == 2
    assert ("1", "first", "passed") in _rows(text)
    assert ("2", "second", "passed") in _rows(text)


def test_a_failure_does_not_stop_the_later_steps(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    touch = f"\"{sys.executable}\" -c \"open(r'{marker}', 'w').close()\""

    code, text = _run(gate.Step("breaks", _exits(1), BACKEND), gate.Step("after", touch, BACKEND))

    assert code == 1
    assert marker.exists()
    assert ("1", "breaks", "failed") in _rows(text)
    assert ("2", "after", "passed") in _rows(text)


def test_exit_three_is_open_only_for_a_step_declared_as_possibly_open() -> None:
    code, text = _run(
        gate.Step("needs an account", _exits(3), BACKEND, may_be_open=True),
        gate.Step("ordinary", _exits(0), BACKEND),
    )
    assert code == 0
    assert ("1", "needs an account", "open") in _rows(text)

    code, text = _run(gate.Step("ordinary", _exits(3), BACKEND))
    assert code == 1
    assert ("1", "ordinary", "failed") in _rows(text)


def test_a_step_that_may_be_open_still_fails_on_any_other_exit_code() -> None:
    code, text = _run(gate.Step("needs an account", _exits(1), BACKEND, may_be_open=True))

    assert code == 1
    assert ("1", "needs an account", "failed") in _rows(text)


def test_an_open_step_is_never_counted_as_passed() -> None:
    _, text = _run(gate.Step("needs an account", _exits(3), BACKEND, may_be_open=True))

    assert "0 passed, 0 failed, 1 open" in text


def test_the_duration_of_each_step_is_printed() -> None:
    _, text = _run(gate.Step("first", _exits(0), BACKEND))

    row = next(line for line in text.splitlines() if line.startswith("| 1 |"))
    assert float(row.split("|")[4]) >= 0.0


@pytest.mark.parametrize("name", ["m1", "m2", "m3", "m4", "m5", "m6"])
def test_a_gate_without_steps_answers_not_implemented(name: str) -> None:
    definition = gate.GATES[name]
    if definition.steps:
        pytest.skip(f"verify-{name} has its steps")

    done = subprocess.run(
        [sys.executable, str(SCRIPT), name], capture_output=True, text=True, check=False
    )

    assert done.returncode == 2
    expected = f"verify-{name}: not implemented in this milestone ({definition.plans})"
    assert expected in done.stderr


def test_an_unknown_gate_is_a_usage_error() -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "m9"], capture_output=True, text=True, check=False
    )

    assert done.returncode == 2
