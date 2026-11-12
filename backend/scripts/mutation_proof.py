"""Apply the mutation catalogue to `pricing/domain` and assert the tests fail (plan 02).

    make mutation-proof
    uv run python scripts/mutation_proof.py [--only <name>] [--json <path>]

No arguments runs the whole catalogue, `--only <name>` runs one mutant, `--json <path>` writes
the result. `--catalogue <file>` reads another catalogue (used by this script's own tests).

The working tree is never modified. The sources are copied to a temporary directory under
`<repository>/.cache/mutation/`; each mutant is applied to its own fresh copy, and the
pricing unit tests run with `PYTHONPATH` pointing at that copy. Before any test run the
script checks that `veranico` is imported from the copy, and it requires the tests to pass
on an unmutated copy first, so a run that tested the working tree by mistake cannot pass.

Results per mutant: `killed` (the tests failed), `SURVIVED` (they passed), `stale` (the text
to replace does not occur exactly once), `error` (pytest could not run).

Exit code: 0 when every mutant is killed and the catalogue has at least 15 entries;
1 on any survivor, stale entry or error, or a catalogue that is too small;
2 when the unmutated baseline fails or the run cannot be set up.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
SOURCES = BACKEND / "src"
DOMAIN = Path("veranico") / "modules" / "pricing" / "domain"
DEFAULT_CATALOGUE = BACKEND / "tests" / "unit" / "pricing" / "mutation_catalogue.py"
WORK_ROOT = REPOSITORY / ".cache" / "mutation"
TESTS = "tests/unit/pricing"
MIN_MUTANTS = 15
TEST_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str
    find: str
    replace: str
    rule: str


@dataclass(frozen=True)
class Outcome:
    name: str
    rule: str
    file: str
    result: str  # killed | SURVIVED | stale | error
    first_failing_test: str | None
    seconds: float


@dataclass(frozen=True)
class TestRun:
    returncode: int | None  # None: timed out
    first_failure: str | None
    tail: str
    seconds: float


def load_catalogue(path: Path) -> list[Mutant]:
    spec = importlib.util.spec_from_file_location("mutation_catalogue", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load the catalogue {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses and NamedTuple look their module up
    spec.loader.exec_module(module)
    mutants = [
        Mutant(entry.name, entry.file, entry.find, entry.replace, entry.rule)
        for entry in module.CATALOGUE
    ]
    names = [mutant.name for mutant in mutants]
    if len(set(names)) != len(names):
        raise ValueError("the catalogue has two mutants with the same name")
    for mutant in mutants:
        target = (DOMAIN / mutant.file).as_posix()
        if ".." in Path(mutant.file).parts or not (SOURCES / target).is_file():
            raise ValueError(f"{mutant.name}: {mutant.file} is not a file of pricing/domain")
    return mutants


def copy_sources(destination: Path) -> Path:
    copy = destination / "src"
    shutil.copytree(SOURCES, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def environment(copy: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(copy)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def imports_the_copy(copy: Path) -> bool:
    """Whether `veranico` resolves to the copy, not to the working tree."""
    probe = subprocess.run(
        [sys.executable, "-c", "import veranico; print(veranico.__file__)"],
        cwd=BACKEND,
        env=environment(copy),
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT_SECONDS,
        check=False,
    )
    return probe.returncode == 0 and Path(probe.stdout.strip()).is_relative_to(copy)


def run_tests(copy: Path) -> TestRun:
    """The pricing unit tests against `copy`, stopping at the first failure."""
    command = [
        sys.executable,
        "-m",
        "pytest",
        TESTS,
        "-m",
        "not slow",
        "-x",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    started = time.monotonic()
    try:
        done = subprocess.run(
            command,
            cwd=BACKEND,
            env=environment(copy),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TestRun(None, "timed out", "", time.monotonic() - started)
    lines = done.stdout.splitlines()
    first = next(
        (line.split(" ")[1] for line in lines if line.startswith(("FAILED ", "ERROR "))), None
    )
    return TestRun(done.returncode, first, "\n".join(lines[-25:]), time.monotonic() - started)


def judge(mutant: Mutant, work: Path) -> Outcome:
    """Apply one mutant to a fresh copy and run the tests against it."""
    source = (SOURCES / DOMAIN / mutant.file).read_text(encoding="utf-8")
    if source.count(mutant.find) != 1 or mutant.find == mutant.replace:
        return Outcome(mutant.name, mutant.rule, mutant.file, "stale", None, 0.0)
    directory = work / mutant.name
    copy = copy_sources(directory)
    try:
        target = copy / DOMAIN / mutant.file
        target.write_text(source.replace(mutant.find, mutant.replace), encoding="utf-8")
        run = run_tests(copy)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if run.returncode == 0:
        result = "SURVIVED"
    elif run.returncode is None or (run.returncode in (1, 2) and run.first_failure is not None):
        result = "killed"  # a test failed, a test module no longer imports, or it hung
    else:
        result = "error"
    return Outcome(mutant.name, mutant.rule, mutant.file, result, run.first_failure, run.seconds)


def print_table(outcomes: list[Outcome]) -> None:
    headers = ("mutant", "rule", "file", "result", "first failing test", "seconds")
    rows = [
        (
            outcome.name,
            outcome.rule,
            outcome.file,
            outcome.result,
            outcome.first_failing_test or "-",
            f"{outcome.seconds:.1f}",
        )
        for outcome in outcomes
    ]
    widths = [max(len(row[column]) for row in [headers, *rows]) for column in range(len(headers))]
    for row in [headers, tuple("-" * width for width in widths), *rows]:
        cells = (cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        print("  ".join(cells).rstrip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the mutation catalogue.")
    parser.add_argument("--only", metavar="NAME")
    parser.add_argument("--json", metavar="PATH", type=Path)
    parser.add_argument("--catalogue", metavar="FILE", type=Path, default=DEFAULT_CATALOGUE)
    arguments = parser.parse_args(argv)

    try:
        catalogue = load_catalogue(arguments.catalogue)
    except (OSError, ValueError, AttributeError) as error:
        print(f"mutation_proof: {error}", file=sys.stderr)
        return 2
    selected = catalogue
    if arguments.only is not None:
        selected = [mutant for mutant in catalogue if mutant.name == arguments.only]
        if not selected:
            print(f"mutation_proof: no mutant named {arguments.only}", file=sys.stderr)
            return 2

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=WORK_ROOT))
    try:
        baseline_copy = copy_sources(work / "baseline")
        if not imports_the_copy(baseline_copy):
            print("mutation_proof: the tests would not import the copied sources", file=sys.stderr)
            return 2
        baseline = run_tests(baseline_copy)
        if baseline.returncode != 0:
            print("mutation_proof: the unmutated baseline fails", file=sys.stderr)
            print(baseline.tail, file=sys.stderr)
            return 2
        outcomes = [judge(mutant, work) for mutant in selected]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    counts = {
        result: sum(1 for outcome in outcomes if outcome.result == result)
        for result in ("killed", "SURVIVED", "stale", "error")
    }
    too_small = len(catalogue) < MIN_MUTANTS
    passed = counts["killed"] == len(outcomes) and not too_small
    print_table(outcomes)
    summary = (
        f"mutation proof: {len(outcomes)} mutants, {counts['killed']} killed, "
        f"{counts['SURVIVED']} survived, {counts['stale']} stale, {counts['error']} errors "
        f"(catalogue of {len(catalogue)}, baseline passed in {baseline.seconds:.1f}s)"
    )
    print(summary)
    if too_small:
        print(f"mutation proof: the catalogue needs at least {MIN_MUTANTS} mutants")
    if arguments.json is not None:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "catalogue_size": len(catalogue),
                    "minimum_catalogue_size": MIN_MUTANTS,
                    "tests": TESTS,
                    "baseline_seconds": round(baseline.seconds, 1),
                    "killed": counts["killed"],
                    "survived": counts["SURVIVED"],
                    "stale": counts["stale"],
                    "errors": counts["error"],
                    "mutants": [
                        {**asdict(outcome), "seconds": round(outcome.seconds, 1)}
                        for outcome in outcomes
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
