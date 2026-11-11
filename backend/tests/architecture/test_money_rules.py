"""The money rules of SPEC 5.7, checked on the syntax tree.

* No contract field with a money name is annotated `float`.
* Outside `pricing`: no `round(`, no `Decimal(`, and no arithmetic operator applied to a
  name or attribute ending in `_cents`.
"""

import ast
import fnmatch
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
PACKAGE = BACKEND / "src" / "veranico"
VIOLATIONS = Path(__file__).resolve().parent / "_violations" / "money"

MONEY_NAMES = (
    "*_cents",
    "premium",
    "limit",
    "payout*",
    "burn_cost",
    "expected_loss",
    "std_dev",
    "gap_to_burn_cost",
)


def is_money_name(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in MONEY_NAMES)


def _mentions_float(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        annotation = ast.parse(annotation.value, mode="eval").body  # a quoted annotation
    return any(isinstance(node, ast.Name) and node.id == "float" for node in ast.walk(annotation))


def float_money_fields(root: Path) -> list[str]:
    """`<file>:<line>: <Class>.<field>` for every money field of a contract typed `float`.

    Contracts are every `contracts.py`, the wire schemas (`http/schemas.py`) and the kernel.
    """
    files = [*root.rglob("contracts.py"), *root.rglob("http/schemas.py")]
    files += list((root / "shared" / "kernel").glob("*.py"))
    found = []
    for path in sorted(set(files)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for statement in cls.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and is_money_name(statement.target.id)
                    and _mentions_float(statement.annotation)
                ):
                    where = f"{path.relative_to(root).as_posix()}:{statement.lineno}"
                    found.append(f"{where}: {cls.name}.{statement.target.id}")
    return found


def _is_cents(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id.endswith("_cents")
    if isinstance(node, ast.Attribute):
        return node.attr.endswith("_cents")
    return False


def _called(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _violation(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and _called(node) in {"round", "Decimal"}:
        return f"{_called(node)}("
    operands: list[ast.expr] = []
    if isinstance(node, ast.BinOp):
        operands = [node.left, node.right]
    elif isinstance(node, ast.AugAssign):
        operands = [node.target, node.value]
    elif isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
        operands = [node.operand]
    if any(_is_cents(operand) for operand in operands):
        return "arithmetic on a *_cents value"
    return None


def money_arithmetic(root: Path) -> list[str]:
    """`<file>:<line>: <what>` for rounding and money arithmetic outside `pricing`."""
    found = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[:2] == ("modules", "pricing"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            what = _violation(node)
            if what is not None:
                line = getattr(node, "lineno", 0)
                found.append((relative.as_posix(), line, what))
    return [f"{file}:{line}: {what}" for file, line, what in sorted(found)]


@pytest.mark.req("R-5.7-4", "R-16.2-4")
def test_no_contract_field_with_a_money_name_is_a_float() -> None:
    assert len(list(PACKAGE.rglob("contracts.py"))) == 7
    assert float_money_fields(PACKAGE) == []


@pytest.mark.req("R-5.7-4", "R-16.2-4")
def test_no_rounding_or_money_arithmetic_outside_pricing() -> None:
    assert money_arithmetic(PACKAGE) == []


@pytest.mark.req("R-16.2-4")
def test_the_field_scan_reports_every_float_money_field_of_the_violating_tree() -> None:
    assert float_money_fields(VIOLATIONS) == [
        "modules/quoting/contracts.py:7: Money.amount_cents",
        "modules/quoting/contracts.py:11: Priced.premium",
        "modules/quoting/contracts.py:12: Priced.limit",
        "modules/quoting/contracts.py:13: Priced.payout_1_in_10",
        "modules/quoting/contracts.py:14: Priced.burn_cost",
        "modules/quoting/contracts.py:15: Priced.expected_loss",
        "modules/quoting/contracts.py:16: Priced.std_dev",
        "modules/quoting/contracts.py:17: Priced.gap_to_burn_cost",
    ]


@pytest.mark.req("R-16.2-4")
def test_the_arithmetic_scan_reports_the_violating_tree_and_leaves_pricing_alone() -> None:
    assert money_arithmetic(VIOLATIONS) == [
        "modules/quoting/application/totals.py:12: round(",
        "modules/quoting/application/totals.py:16: Decimal(",
        "modules/quoting/application/totals.py:20: Decimal(",
        "modules/quoting/application/totals.py:24: arithmetic on a *_cents value",
        "modules/quoting/application/totals.py:28: arithmetic on a *_cents value",
        "modules/quoting/application/totals.py:34: arithmetic on a *_cents value",
        "modules/quoting/application/totals.py:39: arithmetic on a *_cents value",
    ]


@pytest.mark.parametrize(
    ("name", "money"),
    [
        ("amount_cents", True),
        ("limit_cents", True),
        ("premium", True),
        ("limit", True),
        ("payout", True),
        ("payout_1_in_100", True),
        ("burn_cost", True),
        ("expected_loss", True),
        ("std_dev", True),
        ("gap_to_burn_cost", True),
        ("index_value", False),
        ("trigger", False),
        ("rate_on_line", False),
        ("slope_per_decade", False),
    ],
)
def test_money_names(name: str, money: bool) -> None:
    assert is_money_name(name) is money


@pytest.mark.req("R-5.7-4")
def test_the_contract_money_fields_are_money_or_integers() -> None:
    """The positive side: the money fields that exist are `Money`, never a bare number."""
    annotations: dict[str, set[str]] = {}
    for path in PACKAGE.rglob("contracts.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and is_money_name(node.target.id)
            ):
                annotations.setdefault(node.target.id, set()).add(ast.unparse(node.annotation))

    assert annotations["premium"] <= {"Money", "Premium"}
    assert annotations["limit"] == {"Money"}
    assert annotations["burn_cost"] == annotations["expected_loss"] == {"Money"}
    assert annotations["std_dev"] == annotations["gap_to_burn_cost"] == {"Money"}
    assert annotations["payout"] == {"Money | None"}
