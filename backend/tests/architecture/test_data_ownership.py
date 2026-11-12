"""Data ownership (SPEC 3.1 and 14, contracts section 9): a module names only the Firestore
collections and the Cloud Storage prefixes it owns.

The scan reads string literals, f-strings included. Docstrings are prose and are skipped.
A literal is a collection name when a path segment of it is `<module>_<word>`; it is a
storage prefix when it starts with `<module>/`.
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODULES_DIR = BACKEND / "src" / "veranico" / "modules"
VIOLATIONS = Path(__file__).resolve().parent / "_violations" / "data_ownership" / "modules"

# contracts.md section 9.
COLLECTIONS: dict[str, set[str]] = {
    "access": {"access_workspaces", "access_api_keys", "access_allowances", "access_spend"},
    "climate": set(),
    "pricing": set(),
    "quoting": {"quoting_quotes", "quoting_idempotency", "quoting_outbox"},
    "carriers": {"carriers_receipts"},
    "documents": set(),
    "assistant": {"assistant_conversations"},
}
STORAGE_OWNERS = {"climate", "documents"}  # `climate/cubes/`, `climate/points/`, `documents/...`

_MODULES = "|".join(COLLECTIONS)
_COLLECTION = re.compile(rf"\A(?P<module>{_MODULES})_[a-z][a-z_]*\Z")
_PREFIX = re.compile(rf"\A(?P<module>{_MODULES})/")


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def _literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string literal outside docstrings; an f-string gives its leading fixed text."""
    skipped = _docstrings(tree)
    inside_f_strings = {
        id(value)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for value in node.values
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            first = node.values[0] if node.values else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((node.lineno, first.value))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
            and id(node) not in inside_f_strings
        ):
            found.append((node.lineno, node.value))
    return found


def ownership_violations(modules_dir: Path) -> list[str]:
    """`<module>/<file>:<line>: <what>` for every name a module uses and does not own."""
    violations = []
    for path in sorted(modules_dir.rglob("*.py")):
        relative = path.relative_to(modules_dir)
        module = relative.parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, literal in _literals(tree):
            where = f"{relative.as_posix()}:{line}"
            prefix = _PREFIX.match(literal)
            if prefix and (prefix["module"] != module or module not in STORAGE_OWNERS):
                violations.append(f"{where}: storage prefix {prefix['module']}/")
            for segment in literal.split("/"):
                collection = _COLLECTION.match(segment)
                if collection is None:
                    continue
                if collection["module"] != module:
                    violations.append(f"{where}: collection {segment} of {collection['module']}")
                elif segment not in COLLECTIONS[module]:
                    violations.append(f"{where}: collection {segment} is in no ownership table")
    return violations


@pytest.mark.req("R-3.1-12", "R-14-3", "R-16.2-3")
def test_no_module_names_a_collection_or_prefix_it_does_not_own() -> None:
    assert {path.parent.name for path in MODULES_DIR.glob("*/__init__.py")} == set(COLLECTIONS)
    assert ownership_violations(MODULES_DIR) == []


@pytest.mark.req("R-16.2-3")
def test_the_scan_reports_every_violation_of_the_violating_tree() -> None:
    assert ownership_violations(VIOLATIONS) == [
        "quoting/infrastructure/store.py:9: collection access_workspaces of access",
        "quoting/infrastructure/store.py:10: collection access_api_keys of access",
        "quoting/infrastructure/store.py:11: storage prefix climate/",
        "quoting/infrastructure/store.py:12: collection assistant_summaries of assistant",
        "quoting/infrastructure/store.py:16: storage prefix documents/",
    ]


def test_the_scan_accepts_what_a_module_owns_and_skips_docstrings(tmp_path: Path) -> None:
    climate = tmp_path / "climate" / "infrastructure"
    climate.mkdir(parents=True)
    (climate / "store.py").write_text(
        '"""Mentions quoting_quotes and documents/ in prose."""\n'
        'CUBES = "climate/cubes/"\n'
        "def path(cell: str) -> str:\n"
        '    """Also access_spend here."""\n'
        '    return f"climate/points/{cell}"\n'
    )

    assert ownership_violations(tmp_path) == []


def test_the_scan_reports_a_collection_missing_from_the_ownership_table(tmp_path: Path) -> None:
    quoting = tmp_path / "quoting" / "infrastructure"
    quoting.mkdir(parents=True)
    (quoting / "store.py").write_text('NEW = "quoting_archive"\nOWN = "quoting_outbox"\n')

    assert ownership_violations(tmp_path) == [
        "quoting/infrastructure/store.py:1: collection quoting_archive is in no ownership table"
    ]


def test_a_module_without_storage_may_not_name_its_own_prefix(tmp_path: Path) -> None:
    quoting = tmp_path / "quoting" / "infrastructure"
    quoting.mkdir(parents=True)
    (quoting / "store.py").write_text('BLOBS = "quoting/exports/"\n')

    assert ownership_violations(tmp_path) == [
        "quoting/infrastructure/store.py:1: storage prefix quoting/"
    ]
