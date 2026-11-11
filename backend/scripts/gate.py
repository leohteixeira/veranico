"""Run the executable gate of one milestone and print its summary table.

    make verify-m0            (the usual entry point; it loads the owner's `.env` when present)
    uv run python scripts/gate.py m0

Every step runs, also after a failure. Each step is reported as `passed`, `failed` or `open`:

* `passed`  the command exited 0;
* `open`    the command exited 3 and the step is declared as one that may be open: it needs an
            account, a key or the network that is missing here. Open is never passed;
* `failed`  any other exit code, and exit 3 from a step that may not be open.

Exit codes: 0 no step failed, 1 a step failed, 2 the gate is unknown or has no steps yet.

A step that may be open calls its script directly (`uv run python scripts/ingest.py ...`,
`uv run python -m tests.evals.run`), never `make <target>`: GNU Make answers every failed
recipe with exit status 2, so the 3 of the script would be lost and the step reported as
failed. The step still receives the keys, because the gate itself runs under `make verify-m<N>`.

The coordinator fills the step lists of `m1` to `m6` as the plans land.
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"

OPEN_EXIT_CODE = 3


@dataclass(frozen=True)
class Step:
    name: str
    command: str  # run by the shell in `cwd`
    cwd: Path
    may_be_open: bool = False


@dataclass(frozen=True)
class Gate:
    plans: str  # who delivers the steps, for the not-implemented message
    steps: tuple[Step, ...] = ()


# Step 8 goes through Make because the target starts the emulators and stops them afterwards
# when it was the one that started them.
_SMOKE = "make test-integration TESTS=tests/integration/test_emulators_smoke.py"
# `-q` prints nothing: without it the resolved file, with interpolated values, would be shown.
_COMPOSE_CONFIG = (
    "docker compose --env-file /dev/null -p veranico config -q"
    " && docker compose --env-file /dev/null -p veranico --profile failure config -q"
)
_EMULATORS_UP = "docker compose --env-file /dev/null -p veranico up -d --wait firestore storage"
_GITLEAKS = (
    "gitleaks dir . --config .gitleaks.toml --redact --no-banner"
    " && gitleaks git . --config .gitleaks.toml --redact --no-banner"
)

GATES: dict[str, Gate] = {
    "m0": Gate(
        plans="plan 00",
        steps=(
            Step("lint", "make lint", REPO),
            Step("architecture tests", "uv run pytest tests/architecture -q", BACKEND),
            Step("fakes satisfy their Protocols", "uv run pytest tests/fakes -q", BACKEND),
            Step(
                "routes of SPEC 11 in OpenAPI with contract schemas",
                "uv run pytest tests/api/test_openapi_contract.py -q",
                BACKEND,
            ),
            Step("client drift", "make gen-client CHECK=1", REPO),
            Step(
                "frontend type check and build",
                "pnpm --dir frontend typecheck && pnpm --dir frontend build",
                REPO,
            ),
            Step("Compose file", _COMPOSE_CONFIG, REPO),
            Step("emulator smoke test", _SMOKE, REPO),
            Step("/healthz on both roles", "uv run pytest tests/api/test_health.py -q", BACKEND),
            Step("gitleaks", _GITLEAKS, REPO),
        ),
    ),
    "m1": Gate(
        plans="plans 01, 02, 07",
        steps=(
            Step("access unit tests", "uv run pytest tests/unit/access -q", BACKEND),
            Step(
                "access integration and API tests on the emulators",
                'make test-integration TESTS="tests/integration/access tests/api/access"',
                REPO,
            ),
            Step(
                "climate point path tests",
                "uv run pytest tests/unit/climate tests/integration/climate tests/failure/climate"
                ' tests/api/climate -m "not live and not slow and not integration" -q',
                BACKEND,
            ),
            Step(
                "ingest caches one real point (open without network)",
                "uv run python scripts/ingest.py --lat=-9.39 --lon=-40.5",
                BACKEND,
                may_be_open=True,
            ),
            Step(
                "pricing unit and API tests",
                "uv run pytest tests/unit/pricing tests/api/pricing -q",
                BACKEND,
            ),
            Step("mutation proof (at least 15 mutants, all killed)", "make mutation-proof", REPO),
            Step(
                "price_demo backtests and prices a fixture series",
                "uv run python scripts/price_demo.py",
                BACKEND,
            ),
        ),
    ),
    "m2": Gate(
        plans="plans 01, 02",
        steps=(
            Step(
                "NetCDF to Zarr pipeline on the synthetic file, cube store, consistency check",
                "uv run pytest tests/unit/climate/test_cube_build.py"
                " tests/integration/climate/test_cube_store.py"
                " tests/integration/climate/test_consistency.py -q",
                BACKEND,
            ),
            Step(
                "cube store on the Cloud Storage emulator",
                "make test-integration TESTS=tests/integration/climate/test_gcs_store.py",
                REPO,
            ),
            Step(
                "per-cell metrics equal the hand-computed 2 by 2 grid",
                "uv run pytest tests/unit/pricing/test_cells.py"
                " tests/unit/pricing/test_cells_summary.py -q",
                BACKEND,
            ),
            Step(
                "per-cell metrics on a full-size cube in under one second",
                "uv run pytest tests/integration/pricing/test_cell_metrics_speed.py -m slow -q",
                BACKEND,
            ),
        ),
    ),
    "m3": Gate(
        plans="plans 03, 04, 05, 06",
        steps=(
            # The module steps below need the emulators; they are left running afterwards.
            Step("emulators up", _EMULATORS_UP, REPO),
            Step(
                "documents unit, integration and API tests",
                "uv run pytest tests/unit/documents tests/integration/documents"
                ' tests/api/documents -m "not live" -q',
                BACKEND,
            ),
            Step(
                "quoting unit, integration and API tests",
                "uv run pytest tests/unit/quoting tests/integration/quoting"
                ' tests/api/quoting -m "not live" -q',
                BACKEND,
            ),
            Step(
                "carriers unit, integration and API tests",
                "uv run pytest tests/unit/carriers tests/integration/carriers"
                ' tests/api/carriers -m "not live" -q',
                BACKEND,
            ),
            Step(
                "assistant unit, integration, API and failure tests",
                "uv run pytest tests/unit/assistant tests/integration/assistant"
                ' tests/api/assistant tests/failure/assistant -m "not live" -q',
                BACKEND,
            ),
            Step(
                "happy path over HTTP on the real modules, scripted model",
                "uv run pytest tests/api/assistant/test_happy_path_http.py -q",
                BACKEND,
            ),
            Step("failure campaign with the fault proxy", "make test-failure", REPO),
            # Paid: calls the model API, prints the cost and stops at its own spend limit.
            Step(
                "evaluation suite at or above its threshold (open without the model key)",
                "uv run python -m tests.evals.run",
                BACKEND,
                may_be_open=True,
            ),
        ),
    ),
    "m4": Gate(
        plans="plan 08",
        steps=(
            Step(
                "frontend dependencies, lint and type check",
                "pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck",
                FRONTEND,
            ),
            Step("frontend unit tests", "pnpm test", FRONTEND),
            Step("frontend build without the mock layer", "pnpm build", FRONTEND),
            Step(
                "Playwright happy path, embed route and screenshots at 1440 and 390",
                "pnpm e2e",
                FRONTEND,
            ),
            Step(
                "frame-ancestors header of the embed route and of every other page",
                "uv run pytest tests/api/test_static_frontend.py -q",
                BACKEND,
            ),
        ),
    ),
    "m5": Gate(
        plans="plan 09",
        steps=(
            Step("emulators up", _EMULATORS_UP, REPO),
            Step("delivery unit tests", "uv run pytest tests/unit/delivery -q", BACKEND),
            Step(
                "delivery integration tests (spans, redaction, shutdown, Terraform guardrails)",
                'uv run pytest tests/integration/delivery -m "integration and not evidence" -q',
                BACKEND,
            ),
            Step("load fixture and oracle tests", "uv run pytest ../load/tests -q", BACKEND),
            Step(
                "image builds and passes the container smoke test",
                "docker build -t veranico:smoke . && infra/smoke/container_smoke.sh veranico:smoke",
                REPO,
            ),
            Step(
                "Terraform format, validate and tests (nothing is applied)",
                "terraform fmt -check -recursive && terraform init -backend=false -input=false"
                " && terraform validate && terraform test",
                REPO / "infra" / "terraform",
            ),
            Step(
                "workflows pinned and least-privilege",
                "uv run python ../.github/scripts/check_delivery.py workflows",
                BACKEND,
            ),
            Step(
                "no service account key in Terraform",
                "uv run python ../.github/scripts/check_delivery.py terraform-keys",
                BACKEND,
            ),
            Step("load campaign on the local stack", "make load", REPO),
            Step(
                "stored load result passed",
                "uv run pytest tests/integration/delivery/test_load_result.py -m evidence -q",
                BACKEND,
            ),
        ),
    ),
    # The repository part of M6. The portfolio page (plan 10) lives in another repository
    # and is verified there.
    "m6": Gate(
        plans="plans 09, 10",
        steps=(
            Step(
                "traceability, every requirement with a passing test",
                "make traceability REQUIRE_ALL=1",
                REPO,
            ),
            Step("evidence campaigns and the rendered record", "make evidence", REPO),
            Step(
                "verification record matches passed results on HEAD",
                "uv run python scripts/evidence.py check"
                " --require traceability,mutation,failure,load,evals",
                BACKEND,
            ),
            Step(
                "README structure",
                "uv run python ../.github/scripts/check_delivery.py readme",
                BACKEND,
            ),
            # Isolated: its own Compose project, so it runs next to the shared emulators.
            Step(
                "clean copy: verify-m0 and make dev",
                "ISOLATED=1 infra/smoke/clean_copy.sh",
                REPO,
            ),
        ),
    ),
}


def _state(step: Step, returncode: int) -> str:
    if returncode == 0:
        return "passed"
    if returncode == OPEN_EXIT_CODE and step.may_be_open:
        return "open"
    return "failed"


def run_gate(name: str, steps: list[Step], out: TextIO) -> int:
    """Run every step, print the summary table to `out`, return the exit code of the gate."""
    rows: list[tuple[Step, str, float]] = []
    for number, step in enumerate(steps, start=1):
        print(f"\n=== verify-{name} step {number}/{len(steps)}: {step.name}", file=out, flush=True)
        print(f"    $ {step.command}", file=out, flush=True)
        started = time.monotonic()
        done = subprocess.run(step.command, shell=True, cwd=step.cwd, check=False)
        rows.append((step, _state(step, done.returncode), time.monotonic() - started))

    width = max(len(step.name) for step, _, _ in rows)
    print(f"\nverify-{name}\n", file=out)
    print(f"| # | {'Step'.ljust(width)} | Result | Seconds |", file=out)
    print(f"|---|{'-' * (width + 2)}|--------|---------|", file=out)
    for number, (step, state, seconds) in enumerate(rows, start=1):
        print(f"| {number} | {step.name.ljust(width)} | {state} | {seconds:.1f} |", file=out)

    counts = {
        state: sum(1 for _, s, _ in rows if s == state) for state in ("passed", "failed", "open")
    }
    print(
        f"\n{counts['passed']} passed, {counts['failed']} failed, {counts['open']} open",
        file=out,
        flush=True,
    )
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the executable gate of one milestone.")
    parser.add_argument("gate", choices=sorted(GATES))
    arguments = parser.parse_args(argv)

    definition = GATES[arguments.gate]
    if not definition.steps:
        print(
            f"verify-{arguments.gate}: not implemented in this milestone ({definition.plans})",
            file=sys.stderr,
        )
        return 2
    return run_gate(arguments.gate, list(definition.steps), sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
