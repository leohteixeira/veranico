#!/usr/bin/env python3
"""Check modular-monolith boundaries in a Python code base. Standard library only.

Usage:
    python3 validate_boundaries.py [MODULES_DIR] [--public NAME ...] [--strict]

MODULES_DIR is the package that contains one subpackage per business module
(for example src/clinic/modules). When omitted, the first `modules` package found
under ./src or . is used.

Checks (see references/state-isolation.md):
  errors   - cross-module imports outside the public surface (default: <module>.contracts)
           - imports of another module's `module.py` wiring (only the composition root may)
           - layer violations: domain -> application/infrastructure/http/module,
             application -> infrastructure/http/module, domain -> web/ORM/HTTP frameworks
           - shared code importing modules
           - ForeignKey("<schema>.<table>.<column>") into another module's schema
           - the same (schema, table) declared by two modules
  warnings - http <-> infrastructure imports, contracts importing module internals,
             a module's __init__.py importing its internals
           - schema name different from the module name, tables without a schema
           - cycles in the module dependency graph

Exit status: 1 when errors are found (or warnings with --strict), else 0.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

LAYER_RANK = {"domain": 0, "application": 1, "infrastructure": 2, "http": 2, "module": 3}
FORBIDDEN_IN_DOMAIN = {
    "fastapi", "starlette", "sqlalchemy", "pydantic", "pydantic_settings", "httpx", "requests",
    "aiohttp", "alembic", "django", "asyncpg", "psycopg", "psycopg2", "redis", "celery",
}
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".mypy_cache", ".ruff_cache"}


@dataclass
class Finding:
    level: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.level.upper():7} {self.path}:{self.line}  {self.message}"


@dataclass
class Report:
    root: Path
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, path: Path, line: int, message: str) -> None:
        try:
            shown = str(path.relative_to(self.root))
        except ValueError:
            shown = str(path)
        finding = Finding(level, shown, line, message)
        if finding not in self.findings:   # one finding per line, even for multi-name imports
            self.findings.append(finding)

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)


def package_name(directory: Path) -> str:
    """Dotted import name of a directory, walking up while parents are packages."""
    parts = [directory.name]
    current = directory.parent
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent
    return ".".join(reversed(parts))


def find_modules_dir(start: Path) -> Path | None:
    for base in (start / "src", start):
        if not base.is_dir():
            continue
        for candidate in sorted(base.rglob("modules")):
            if any(part in SKIP_DIRS for part in candidate.parts):
                continue
            if candidate.is_dir() and (candidate / "__init__.py").exists():
                return candidate
    return None


def python_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.rglob("*.py") if not any(part in SKIP_DIRS for part in p.parts)
    )




def resolve_imports(tree: ast.AST, path: Path) -> list[tuple[int, str]]:
    """Return (line, dotted target) for every import, resolving relative imports.

    `from pkg import name` yields both `pkg` and `pkg.name`, because `name` may be a
    submodule; callers decide which form matters.
    """
    results: list[tuple[int, str]] = []
    current = package_name(path.parent)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = current.split(".")
                if node.level - 1 > 0:
                    base_parts = base_parts[: -(node.level - 1)] or base_parts[:1]
                base = ".".join(base_parts)
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            for alias in node.names:
                results.append((node.lineno, f"{module}\0{alias.name}"))
    return results


def module_and_layer(path: Path, modules_dir: Path) -> tuple[str, str]:
    relative = path.relative_to(modules_dir).parts
    module = relative[0]
    if len(relative) == 1:
        return module, "root"
    head = relative[1]
    if head.endswith(".py"):
        head = head[:-3]
    if head == "__init__":
        return module, "root"
    return module, head


def str_arg(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def keyword(node: ast.Call, name: str) -> str | None:
    for kw in node.keywords:
        if kw.arg == name:
            return str_arg(kw.value)
    return None


def table_args_schema(value: ast.AST) -> str | None:
    if isinstance(value, ast.Dict):
        for k, v in zip(value.keys, value.values, strict=False):
            if k is not None and str_arg(k) == "schema":
                return str_arg(v)
    if isinstance(value, ast.Tuple) and value.elts:
        return table_args_schema(value.elts[-1])
    return None


@dataclass
class TableDecl:
    module: str
    schema: str | None
    name: str
    path: Path
    line: int


def scan_data(tree: ast.AST, path: Path, module: str, report: Report,
              declared_schemas: dict[str, set[str]], tables: list[TableDecl],
              foreign_keys: list[tuple[str, str, Path, int]]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = call_name(node)
            if name == "MetaData":
                schema = keyword(node, "schema")
                if schema:
                    declared_schemas[module].add(schema)
                    if schema != module:
                        report.add("warning", path, node.lineno,
                                   f"MetaData schema '{schema}' differs from module name '{module}'")
            elif name == "Table" and node.args:
                table = str_arg(node.args[0])
                if table:
                    tables.append(TableDecl(module, keyword(node, "schema"), table, path, node.lineno))
            elif name == "ForeignKey" and node.args:
                target = str_arg(node.args[0])
                if target and target.count(".") == 2:
                    foreign_keys.append((module, target.split(".")[0], path, node.lineno))
        elif isinstance(node, ast.ClassDef):
            table_name: str | None = None
            schema: str | None = None
            line = node.lineno
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    target_name = stmt.targets[0].id
                    if target_name == "__tablename__":
                        table_name = str_arg(stmt.value)
                        line = stmt.lineno
                    elif target_name == "__table_args__":
                        schema = table_args_schema(stmt.value)
            if table_name:
                tables.append(TableDecl(module, schema, table_name, path, line))
                if schema and schema != module:
                    report.add("warning", path, line,
                               f"table '{table_name}' uses schema '{schema}', not the module name '{module}'")


def find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()

    def visit(node: str, stack: list[str]) -> None:
        for nxt in sorted(edges.get(node, ())):
            if nxt in stack:
                cycle = stack[stack.index(nxt):] + [nxt]
                key = tuple(sorted(set(cycle)))
                if key not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(cycle)
            elif len(stack) < 50:
                visit(nxt, [*stack, nxt])

    for start in sorted(edges):
        visit(start, [start])
    return cycles


def check(modules_dir: Path, public: set[str], report: Report) -> str:
    prefix = package_name(modules_dir)
    root_package = prefix.split(".")[0]
    modules = sorted(
        p.name for p in modules_dir.iterdir()
        if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")
        and any(p.rglob("*.py"))
    )
    edges: dict[str, set[str]] = defaultdict(set)
    declared_schemas: dict[str, set[str]] = defaultdict(set)
    tables: list[TableDecl] = []
    foreign_keys: list[tuple[str, str, Path, int]] = []

    def is_submodule(dotted: str) -> bool:
        parts = dotted[len(prefix) + 1:].split(".")
        location = modules_dir.joinpath(*parts)
        return location.with_suffix(".py").is_file() or (location / "__init__.py").is_file()

    for path in python_files(modules_dir):
        if path.parent == modules_dir:
            continue
        module, layer = module_and_layer(path, modules_dir)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            version = ".".join(map(str, sys.version_info[:2]))
            report.add("error", path, exc.lineno or 1,
                       f"cannot parse with Python {version}: {exc.msg} "
                       "(run with the project's interpreter, e.g. `uv run python ...`)")
            continue

        scan_data(tree, path, module, report, declared_schemas, tables, foreign_keys)

        reported_frameworks: set[tuple[int, str]] = set()
        for line, raw in resolve_imports(tree, path):
            if "\0" in raw:
                base, name = raw.split("\0")
                candidates = [base, f"{base}.{name}"] if base else [name]
                inside = candidates[-1].startswith(prefix + ".")
                if base and inside and not is_submodule(candidates[-1]):
                    candidates = [base]   # `from pkg import name` where name is an attribute, not a module
            else:
                candidates = [raw]

            # Framework imports inside the domain.
            if layer == "domain":
                top = candidates[0].split(".")[0]
                if top in FORBIDDEN_IN_DOMAIN and (line, top) not in reported_frameworks:
                    reported_frameworks.add((line, top))
                    report.add("error", path, line,
                               f"domain imports '{top}'; keep frameworks, ORMs, and HTTP clients out of the domain")

            target = next((c for c in reversed(candidates) if c == prefix or c.startswith(prefix + ".")), None)
            if target is None:
                continue
            rest = target[len(prefix) + 1:].split(".") if target != prefix else []
            if not rest:
                continue
            other = rest[0]
            sub = rest[1] if len(rest) > 1 else None

            if other != module:
                if other not in modules:
                    continue
                if sub in public:
                    edges[module].add(other)
                elif sub is None:
                    # `import <prefix>.<other>` or `from <prefix> import <other>`: harmless only
                    # when the package __init__ is empty; flag as a warning.
                    report.add("warning", path, line,
                               f"imports the '{other}' package itself; import '{prefix}.{other}.contracts' explicitly")
                    edges[module].add(other)
                elif sub == "module":
                    report.add("error", path, line,
                               f"imports {prefix}.{other}.module; only the composition root may wire modules")
                else:
                    report.add("error", path, line,
                               f"imports {target} (internals of module '{other}'); depend on "
                               f"{prefix}.{other}.contracts instead")
                continue

            # Same module: layer rules.
            if sub is None or sub == layer:
                continue
            if layer == "root" and path.name == "__init__.py" and sub != "contracts":
                report.add("warning", path, line,
                           f"package __init__ imports '{sub}'; keep it empty so importing contracts does not load internals")
                continue
            if sub == "module" and layer != "module":
                report.add("error", path, line,
                           f"'{layer}' imports the module wiring ({prefix}.{module}.module)")
                continue
            if layer == "contracts" and sub in LAYER_RANK:
                report.add("warning", path, line,
                           f"contracts imports '{sub}'; contracts should not expose module internals")
                continue
            if layer in ("domain", "application") and sub in LAYER_RANK and LAYER_RANK[sub] > LAYER_RANK[layer]:
                report.add("error", path, line,
                           f"'{layer}' imports outer layer '{sub}'; dependencies must point inward")
            elif {layer, sub} == {"http", "infrastructure"}:
                report.add("warning", path, line,
                           f"'{layer}' imports '{sub}'; http and infrastructure should be independent adapters")

    # Shared code must not import modules.
    shared_dir = modules_dir.parent / "shared"
    if shared_dir.is_dir():
        for path in python_files(shared_dir):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for line, raw in resolve_imports(tree, path):
                dotted = raw.replace("\0", ".")
                if dotted == prefix or dotted.startswith(prefix + "."):
                    report.add("error", path, line,
                               f"shared code imports {dotted}; shared must not depend on modules")

    # Schema ownership.
    schema_owner: dict[str, str] = {}
    for module in modules:
        for schema in declared_schemas.get(module, ()):
            schema_owner.setdefault(schema, module)
        schema_owner.setdefault(module, module)

    for module, schema, path, line in foreign_keys:
        owner = schema_owner.get(schema)
        own_schemas = declared_schemas.get(module) or {module}
        if schema not in own_schemas and owner != module:
            whose = f"module '{owner}'" if owner else "another schema"
            report.add("error", path, line,
                       f"ForeignKey into schema '{schema}' ({whose}); reference other modules by ID without a foreign key")

    seen: dict[tuple[str, str], TableDecl] = {}
    for table in tables:
        schema = table.schema or next(iter(sorted(declared_schemas.get(table.module, ()))), None)
        if schema is None:
            report.add("warning", table.path, table.line,
                       f"table '{table.name}' has no schema; give module '{table.module}' its own MetaData(schema=...)")
            schema = "<default>"
        key = (schema, table.name)
        previous = seen.get(key)
        if previous and previous.module != table.module:
            report.add("error", table.path, table.line,
                       f"table '{schema}.{table.name}' is also declared by module '{previous.module}'")
        seen.setdefault(key, table)

    for cycle in find_cycles(edges):
        report.add("warning", modules_dir, 0,
                   "module dependency cycle: " + " -> ".join(cycle)
                   + " (break one direction with integration events)")

    return (
        f"modules package: {prefix} ({len(modules)} modules: {', '.join(modules) or 'none'}); "
        f"root package: {root_package}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("modules_dir", nargs="?", help="package containing one subpackage per module")
    parser.add_argument("--public", nargs="+", default=["contracts"],
                        help="submodule names other modules may import (default: contracts)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)

    if args.modules_dir:
        modules_dir = Path(args.modules_dir).resolve()
    else:
        found = find_modules_dir(Path.cwd())
        if found is None:
            print("validate_boundaries: no 'modules' package found; pass MODULES_DIR explicitly")
            return 0
        modules_dir = found.resolve()
    if not modules_dir.is_dir():
        print(f"validate_boundaries: '{modules_dir}' is not a directory")
        return 2

    report = Report(root=modules_dir.parent)
    header = check(modules_dir, set(args.public), report)

    print(header)
    for finding in sorted(report.findings, key=lambda f: (f.level != "error", f.path, f.line)):
        print(finding.render())
    errors, warnings = report.count("error"), report.count("warning")
    print(f"validate_boundaries: {errors} error(s), {warnings} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
