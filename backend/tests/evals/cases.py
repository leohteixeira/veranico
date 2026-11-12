"""The cases file: `cases.yaml` as validated values."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.evals.checks import CHECKS, Locale

CASES_FILE = Path(__file__).resolve().parent / "cases.yaml"
LOCALES: tuple[Locale, ...] = ("en", "pt-BR")


class CasesFileError(ValueError):
    """The cases file names something the suite does not know."""


@dataclass(frozen=True)
class Case:
    id: str
    locale: Locale
    turns: tuple[str, ...]
    checks: dict[str, Any]  # check name to its parameters, `answers_in` included
    req: tuple[str, ...]


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [_case(entry) for entry in document["cases"]]
    identifiers = [case.id for case in cases]
    repeated = sorted({name for name in identifiers if identifiers.count(name) > 1})
    if repeated:
        raise CasesFileError(f"case identifiers used twice: {repeated}")
    return cases


def select(cases: list[Case], identifiers: list[str] | None) -> list[Case]:
    """The cases named by `identifiers`, in the order of the file; all of them for `None`."""
    if identifiers is None:
        return cases
    unknown = sorted(set(identifiers) - {case.id for case in cases})
    if unknown:
        raise CasesFileError(f"unknown cases: {unknown}")
    return [case for case in cases if case.id in identifiers]


def _case(entry: dict[str, Any]) -> Case:
    identifier = entry.get("id", "<no id>")
    if entry.get("locale") not in LOCALES:
        raise CasesFileError(f"{identifier}: locale must be one of {LOCALES}")
    turns = entry.get("turns") or []
    if not turns or not all(isinstance(turn, str) and turn.strip() for turn in turns):
        raise CasesFileError(f"{identifier}: needs at least one user turn, each a text")
    checks = dict(entry.get("checks") or {})
    unknown = sorted(set(checks) - set(CHECKS))
    if unknown:
        raise CasesFileError(f"{identifier}: unknown checks {unknown}")
    if "answers_in" in checks:
        raise CasesFileError(f"{identifier}: answers_in comes from the locale, do not declare it")
    if not checks:
        raise CasesFileError(f"{identifier}: declares no check")
    req = entry.get("req") or []
    if not req:
        raise CasesFileError(f"{identifier}: names no requirement")
    return Case(
        id=identifier,
        locale=entry["locale"],
        turns=tuple(turn.strip() for turn in turns),
        checks={**checks, "answers_in": entry["locale"]},
        req=tuple(req),
    )
