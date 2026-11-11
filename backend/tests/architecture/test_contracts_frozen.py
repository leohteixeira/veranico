"""The module contracts are frozen: each `contracts.py` must equal its snapshot.

`frozen_contracts/<module>.txt` holds the code blocks of the frozen contracts document
(sections 2 to 8), copied verbatim. The comparison is made on the syntax tree, so comments
and layout are free, while a changed field name, annotation, default, base class, method
name, parameter, return type or `async` keyword fails here. Changing a contract needs an ADR
that names every consumer; the snapshot changes in that same commit.
"""

import ast
import importlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODULES_DIR = BACKEND / "src" / "veranico" / "modules"
SNAPSHOTS = Path(__file__).resolve().parent / "frozen_contracts"
MODULES = ["access", "climate", "pricing", "quoting", "carriers", "documents", "assistant"]


def definitions(source: str) -> dict[str, str]:
    """Top-level classes and assignments of a source text: name -> syntax tree dump."""
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            assert isinstance(target, ast.Name), ast.dump(node)
            name = target.id
        elif isinstance(node, ast.Import | ast.ImportFrom):
            continue
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the module docstring
        else:
            raise AssertionError(f"unexpected top-level statement: {ast.dump(node)}")
        assert name not in found, f"{name} is defined twice"
        found[name] = ast.dump(node)
    return found


def contract_source(module: str) -> str:
    return (MODULES_DIR / module / "contracts.py").read_text(encoding="utf-8")


def snapshot_source(module: str) -> str:
    return (SNAPSHOTS / f"{module}.txt").read_text(encoding="utf-8")


def test_every_module_has_a_snapshot_and_nothing_else_does() -> None:
    on_disk = sorted(path.name for path in MODULES_DIR.iterdir() if path.is_dir())
    on_disk = [name for name in on_disk if not name.startswith("__")]

    assert on_disk == sorted(MODULES)
    assert sorted(path.stem for path in SNAPSHOTS.glob("*.txt")) == sorted(MODULES)


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.req("R-3.1-14")
def test_contract_defines_exactly_the_frozen_names_in_order(module: str) -> None:
    assert list(definitions(contract_source(module))) == list(definitions(snapshot_source(module)))


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.req("R-3.1-14")
def test_every_definition_equals_its_frozen_form(module: str) -> None:
    actual = definitions(contract_source(module))
    frozen = definitions(snapshot_source(module))

    changed = [name for name in frozen if actual.get(name) != frozen[name]]

    assert changed == [], f"{module}/contracts.py differs from the frozen contract in {changed}"


@pytest.mark.parametrize("module", MODULES)
def test_contract_module_imports(module: str) -> None:
    """Every annotation resolves: Pydantic builds the models when the module is imported."""
    importlib.import_module(f"veranico.modules.{module}.contracts")


# The comparison itself must not be vacuous: each kind of edit has to be noticed.
BASE = """
class Money(BaseModel, frozen=True):
    amount_cents: int
    currency: Literal["BRL"] = "BRL"

class Facade(Protocol):
    async def price(self, dataset_id: DatasetId, cover: Cover) -> Priced: ...
    def catalog(self) -> Catalog: ...
"""


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("amount_cents: int", "amount: int"),
        ("amount_cents: int", "amount_cents: float"),
        ('= "BRL"', '= "USD"'),
        ('currency: Literal["BRL"] = "BRL"', 'currency: Literal["BRL"]'),
        ("frozen=True", "frozen=False"),
        ("async def price", "def price"),
        ("def catalog", "async def catalog"),
        ("cover: Cover", "cover: Cover, options: Options"),
        ("dataset_id: DatasetId, cover: Cover", "cover: Cover, dataset_id: DatasetId"),
        ("-> Priced", "-> Priced | None"),
        ("def catalog", "def directory"),
        ('    currency: Literal["BRL"] = "BRL"\n', ""),
    ],
)
def test_comparison_notices_an_edit(old: str, new: str) -> None:
    assert old in BASE
    assert definitions(BASE.replace(old, new)) != definitions(BASE)


def test_comparison_ignores_comments_and_layout() -> None:
    reformatted = BASE.replace(
        "amount_cents: int", "amount_cents: int  # integer centavos"
    ).replace(
        "self, dataset_id: DatasetId, cover: Cover",
        "\n        self,\n        dataset_id: DatasetId,\n        cover: Cover,\n    ",
    )

    assert reformatted != BASE
    assert definitions(reformatted) == definitions(BASE)
