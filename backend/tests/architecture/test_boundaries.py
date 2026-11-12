"""Module boundaries (SPEC 3.1, 16.2): import-linter, the boundary script, and the check that
no module is missing from an import-linter list."""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODULES_DIR = BACKEND / "src" / "veranico" / "modules"
VIOLATIONS = Path(__file__).resolve().parent / "_violations" / "boundaries" / "shop" / "modules"
SCRIPT = BACKEND / "scripts" / "validate_boundaries.py"
PREFIX = "veranico.modules."
LAYERS = ("domain", "application", "infrastructure", "http")

# SPEC 3.1: the modules whose contracts each module may import.
MAY_IMPORT: dict[str, set[str]] = {
    "access": set(),
    "climate": {"access"},
    "pricing": {"climate"},
    "quoting": {"pricing", "climate", "access"},
    "carriers": {"quoting"},
    "documents": {"quoting", "climate", "access"},
    "assistant": {"access", "climate", "pricing", "quoting", "carriers", "documents"},
}
DIRECTION_REQUIREMENTS = [f"R-3.1-{n}" for n in range(1, 8)]


def module_directories() -> set[str]:
    return {path.parent.name for path in MODULES_DIR.glob("*/__init__.py")}


def contracts() -> dict[str, dict[str, Any]]:
    document = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    return {contract["id"]: contract for contract in document["tool"]["importlinter"]["contracts"]}


def names(values: list[str]) -> set[str]:
    assert all(value.startswith(PREFIX) for value in values), values
    return {value.removeprefix(PREFIX) for value in values}


def run(*command: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command], capture_output=True, text=True, cwd=BACKEND, check=False
    )


@pytest.mark.req("R-3-1")
def test_the_seven_modules_exist() -> None:
    assert module_directories() == set(MAY_IMPORT)


@pytest.mark.req(*DIRECTION_REQUIREMENTS, "R-3.1-8", "R-3.1-9", "R-3.1-10", "R-16.2-1")
def test_import_linter_keeps_every_contract() -> None:
    result = run(Path(sys.executable).parent / "lint-imports")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


@pytest.mark.req("R-16.2-2")
def test_boundary_script_reports_nothing_in_strict_mode() -> None:
    result = run(sys.executable, SCRIPT, "src/veranico/modules", "--strict")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 modules" in result.stdout
    assert "0 error(s), 0 warning(s)" in result.stdout


@pytest.mark.req("R-16.2-2")
def test_boundary_script_reports_a_violating_tree() -> None:
    result = run(sys.executable, SCRIPT, VIOLATIONS, "--strict")

    assert result.returncode == 1
    assert "internals of module 'beta'" in result.stdout
    assert "domain imports 'pydantic'" in result.stdout
    assert "'domain' imports outer layer 'application'" in result.stdout
    assert "3 error(s)" in result.stdout


# Every module directory is named in every import-linter list. A module missing from a
# list would simply not be checked, and import-linter would still report "kept".


@pytest.mark.req("R-16.2-1")
def test_the_expected_contracts_exist() -> None:
    direction = {f"contract-direction-{module}" for module in MAY_IMPORT if module != "assistant"}

    assert set(contracts()) == {
        "shared-below-modules",
        "modules-independent",
        "module-layers",
        "contracts-are-leaf",
        "domain-pure",
        "wiring-only-in-bootstrap",
        *direction,
    }


@pytest.mark.req("R-16.2-1")
def test_independence_and_layers_name_every_module_directory() -> None:
    found = contracts()

    assert names(found["modules-independent"]["modules"]) == module_directories()
    assert names(found["module-layers"]["containers"]) == module_directories()
    assert found["modules-independent"]["ignore_imports"] == [
        "veranico.modules.** -> veranico.modules.*.contracts"
    ]
    assert found["module-layers"]["layers"] == [
        "module",
        "http : infrastructure",
        "application",
        "domain",
    ]


@pytest.mark.req(*DIRECTION_REQUIREMENTS)
@pytest.mark.parametrize("module", sorted(MAY_IMPORT))
def test_direction_contract_forbids_exactly_what_the_spec_does_not_allow(module: str) -> None:
    forbidden = module_directories() - {module} - MAY_IMPORT[module]
    contract = contracts().get(f"contract-direction-{module}")

    if not forbidden:
        # `assistant` may import every other module, so there is nothing to forbid.
        assert contract is None
        return
    assert contract is not None
    assert contract["type"] == "forbidden"
    assert names(contract["source_modules"]) == {module}
    assert names(contract["forbidden_modules"]) == forbidden


@pytest.mark.req("R-16.2-1")
def test_wildcard_contracts_cover_every_module_and_layer() -> None:
    found = contracts()

    assert found["contracts-are-leaf"]["source_modules"] == ["veranico.modules.*.contracts"]
    assert set(found["contracts-are-leaf"]["forbidden_modules"]) == {
        f"veranico.modules.*.{part}" for part in (*LAYERS, "module")
    }
    assert found["domain-pure"]["source_modules"] == ["veranico.modules.*.domain"]
    assert {"fastapi", "pydantic", "httpx", "google", "anthropic"} <= set(
        found["domain-pure"]["forbidden_modules"]
    )
    assert set(found["wiring-only-in-bootstrap"]["source_modules"]) == {
        "veranico.main",
        "veranico.shared",
        *(f"veranico.modules.*.{part}" for part in ("contracts", *LAYERS)),
    }
    assert found["wiring-only-in-bootstrap"]["forbidden_modules"] == ["veranico.modules.*.module"]
    assert found["shared-below-modules"]["source_modules"] == ["veranico.shared"]
    assert found["shared-below-modules"]["forbidden_modules"] == ["veranico.modules"]


@pytest.mark.req("R-3.1-9")
@pytest.mark.parametrize("module", sorted(MAY_IMPORT))
def test_every_module_has_the_layer_packages_the_contracts_name(module: str) -> None:
    directory = MODULES_DIR / module

    assert (directory / "contracts.py").is_file()
    assert (directory / "module.py").is_file()
    for layer in LAYERS:
        assert (directory / layer / "__init__.py").is_file(), layer
    unexpected = {
        path.name
        for path in directory.iterdir()
        if path.name not in {*LAYERS, "contracts.py", "module.py", "__init__.py", "__pycache__"}
    }
    # A directory outside the layers would be outside the layers contract.
    assert unexpected <= {"replays"}, unexpected  # recorded replays of `assistant` (plan 06)


def has_code(path: Path) -> bool:
    """True when the file holds anything but comments and a docstring."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return bool(body)


@pytest.mark.req("R-3.1-8")
def test_every_init_file_of_a_module_stays_empty(tmp_path: Path) -> None:
    init_files = sorted(MODULES_DIR.rglob("__init__.py"))

    assert len(init_files) >= 1 + 7 * 5
    assert [str(path) for path in init_files if has_code(path)] == []

    # The check notices a re-export.
    exporting = tmp_path / "__init__.py"
    exporting.write_text('"""Docstring."""\nfrom .domain import thing\n')
    documented = tmp_path / "documented.py"
    documented.write_text('"""Only a docstring."""\n# and a comment\n')
    assert has_code(exporting)
    assert not has_code(documented)
