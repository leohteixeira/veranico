"""Rules of SPEC 16.9 and 17 that are held by the repository itself, not by a module.

Two kinds of test:

* a wrapper runs a tool exactly as `make lint` or the gate does and fails on a non-zero exit
  (ruff, mypy, eslint, the TypeScript compiler, gitleaks), so the rule enters the
  traceability matrix. They are marked `external`, like the Terraform wrapper, and a missing
  tool is a failure, not a skip;
* a static check reads a committed file (a workflow, `compose.yaml`, `lefthook.yml`, the
  `Makefile`) and asserts what the specification says about it.

    uv run pytest tests/unit/delivery/test_repository_rules.py -q
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[3]
REPOSITORY = BACKEND.parent
FRONTEND = REPOSITORY / "frontend"
WORKFLOWS = REPOSITORY / ".github" / "workflows"


def _run(command: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def _passes(command: list[str], cwd: Path) -> None:
    result = _run(command, cwd)
    assert result.returncode == 0, f"{' '.join(command)}:\n{result.stdout}\n{result.stderr}"


def _pnpm(script: str) -> None:
    if shutil.which("pnpm") is None:
        pytest.fail(f"pnpm is not installed: `pnpm {script}` cannot be checked")
    if not (FRONTEND / "node_modules").is_dir():
        pytest.fail("frontend/node_modules is missing: run `pnpm --dir frontend install` first")
    _passes(["pnpm", "--dir", str(FRONTEND), script], REPOSITORY)


def _workflow(name: str) -> dict[Any, Any]:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def _commands(workflow: dict[Any, Any]) -> str:
    """Every `run` of the workflow, one after the other."""
    return "\n".join(str(step["run"]) for step in _steps(workflow) if "run" in step)


def _recipe(target: str) -> str:
    """The recipe lines of one Makefile target."""
    lines = (REPOSITORY / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"{re.escape(target)}:", line))
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    return "\n".join(recipe)


# --- SPEC 16.9: static checks ----------------------------------------------------------


@pytest.mark.external
@pytest.mark.req("R-16.9-1")
def test_ruff_lint_and_format_checks_pass() -> None:
    _passes([sys.executable, "-m", "ruff", "check", "."], BACKEND)
    _passes([sys.executable, "-m", "ruff", "format", "--check", "."], BACKEND)


@pytest.mark.external
@pytest.mark.req("R-16.9-2")
def test_mypy_strict_passes() -> None:
    configuration = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    mypy_section = configuration.split("[tool.mypy]")[1].split("\n[")[0]
    assert re.search(r"^strict = true$", mypy_section, re.MULTILINE)

    # No argument: the files and the options come from `[tool.mypy]`, as in `make lint`.
    _passes([sys.executable, "-m", "mypy"], BACKEND)


@pytest.mark.external
@pytest.mark.req("R-16.9-3")
def test_eslint_passes() -> None:
    scripts = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["lint"] == "eslint ."

    _pnpm("lint")


@pytest.mark.external
@pytest.mark.req("R-16.9-4")
def test_typescript_strict_passes() -> None:
    options = json.loads((FRONTEND / "tsconfig.json").read_text(encoding="utf-8"))
    assert options["compilerOptions"]["strict"] is True
    scripts = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["typecheck"] == "tsc --noEmit"

    _pnpm("typecheck")


@pytest.mark.req("R-16.9-5")
def test_gitleaks_is_a_pre_commit_hook_and_scans_the_full_history_in_ci() -> None:
    hooks = yaml.safe_load((REPOSITORY / "lefthook.yml").read_text(encoding="utf-8"))
    hook_commands = [job["run"] for job in hooks["pre-commit"]["jobs"]]
    assert any(
        command.startswith("gitleaks git") and "--staged" in command and "--redact" in command
        for command in hook_commands
    ), hook_commands

    ci = _workflow("ci.yml")
    scanning = [
        job
        for job in ci["jobs"].values()
        if any(
            re.search(r'"\$GITLEAKS_IMAGE" git \. --redact', str(step.get("run", "")))
            for step in job["steps"]
        )
    ]
    assert len(scanning) == 1
    assert "gitleaks" in ci["env"]["GITLEAKS_IMAGE"]
    # Without the whole history the scan would see one commit.
    checkout = next(
        step
        for step in scanning[0]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0


@pytest.mark.external
@pytest.mark.req("R-16.9-5")
def test_gitleaks_finds_nothing_in_the_full_history() -> None:
    if not (REPOSITORY / ".git").exists():
        pytest.skip("not a Git work tree: there is no history to scan")
    if shutil.which("gitleaks") is None:
        pytest.skip("gitleaks is not installed here; CI runs the scan from its pinned image")

    result = _run(
        ["gitleaks", "git", ".", "--config", ".gitleaks.toml", "--redact", "--no-banner"],
        REPOSITORY,
    )

    # `--redact` keeps a found value out of this message.
    assert result.returncode == 0, result.stderr[-4000:]
    scanned = re.search(r"(\d+) commits scanned", result.stderr)
    assert scanned is not None, result.stderr[-4000:]
    assert int(scanned.group(1)) > 0


# --- SPEC 17: workflows ---------------------------------------------------------------


@pytest.mark.req("R-17-7")
def test_ci_runs_every_check_on_every_push_and_pull_request() -> None:
    ci = _workflow("ci.yml")

    # No branch, tag or path filter on either trigger.
    assert _triggers(ci) == {"push": None, "pull_request": None}

    commands = _commands(ci)
    lines = {line.strip() for line in commands.splitlines()}
    # Whole lines: `make test` must not be satisfied by `make test-integration`.
    for command in (
        "make lint",
        "make test",
        "make test-integration",
        "make test-failure",
        "make mutation-proof",
        "pnpm --dir frontend build",
        "terraform -chdir=infra/terraform fmt -check -recursive",
        "terraform -chdir=infra/terraform validate",
        "terraform -chdir=infra/terraform test",
    ):
        assert command in lines, f"ci.yml does not run: {command}"
    assert '"$GITLEAKS_IMAGE" git . --redact' in commands

    # What the Make targets stand for: lint, types and the architecture checks; unit and
    # architecture tests and the frontend tests; integration and failure tests.
    lint = _recipe("lint")
    for tool in ("ruff check", "ruff format --check", "mypy", "lint-imports", "frontend lint"):
        assert tool in lint, f"`make lint` does not run {tool}"
    test = _recipe("test")
    assert "pytest tests" in test
    assert "pnpm --dir frontend test" in test
    assert (BACKEND / "tests" / "architecture").is_dir()
    assert "-m integration" in _recipe("test-integration")
    assert "pytest tests/failure -m failure" in _recipe("test-failure")


@pytest.mark.req("R-17-8")
def test_the_evaluation_load_and_deploy_workflows_run_what_the_specification_says() -> None:
    evals = _workflow("evals.yml")
    assert "make evals" in _commands(evals)
    assert "tests.evals.run" in _recipe("evals")

    load = _workflow("load.yml")
    assert _triggers(load) == {"workflow_dispatch": None}  # on demand, and nothing else
    assert "make load" in _commands(load)

    deploy = _workflow("deploy.yml")
    assert _triggers(deploy) == {"push": {"tags": ["v*.*.*"]}}
    (job,) = deploy["jobs"].values()
    release = "${{ github.ref_name }}"
    assert job["env"]["IMAGE_TAG"] == release
    commands = _commands(deploy)
    assert re.search(r"docker build .*--tag \"\$image\"", commands)
    assert 'docker push "$image"' in commands
    assert re.search(r'image=".*:\$\{IMAGE_TAG\}"', commands)
    (apply,) = [
        step for step in job["steps"] if re.search(r"terraform .* apply ", str(step.get("run", "")))
    ]
    assert apply["env"]["TF_VAR_image_tag"] == release
    # Build and push come before the apply that points the services at the new tag.
    assert commands.index("docker push") < commands.index(" apply ")


# --- SPEC 17: development stack ---------------------------------------------------------


def _host_ports(service: dict[str, Any]) -> set[int]:
    """Published host ports of a service, with `${NAME:-default}` read as its default."""
    ports = set()
    for entry in service.get("ports", []):
        host = re.sub(r"\$\{\w+:-(\d+)\}", r"\1", str(entry)).rsplit(":", 1)[0]
        ports.add(int(host.rsplit(":", 1)[-1]))
    return ports


@pytest.mark.req("R-17-9")
def test_the_development_stack_has_the_declared_services_and_ports() -> None:
    compose = yaml.safe_load((REPOSITORY / "compose.yaml").read_text(encoding="utf-8"))
    services: dict[str, dict[str, Any]] = compose["services"]

    always = {name: s for name, s in services.items() if "profiles" not in s}
    assert {name: _host_ports(s) for name, s in always.items() if _host_ports(s)} == {
        "web": {3500},
        "api": {8500},
        "carrier": {8510},
        "jaeger": {8516},
        "firestore": {8580},
        "storage": {8590},
    }
    # The Vite dev server, and the two roles of the one image.
    assert services["web"]["command"] == ["pnpm", "exec", "vite"]
    assert "APP_ROLE=api" in services["api"]["environment"]
    assert "APP_ROLE=carrier" in services["carrier"]["environment"]
    assert services["api"]["image"] == services["carrier"]["image"]

    # The fault proxy is the only service of a profile, so `make dev` never starts it.
    profiled = {name: s for name, s in services.items() if "profiles" in s}
    assert set(profiled) == {"toxiproxy"}
    assert profiled["toxiproxy"]["profiles"] == ["failure"]
    assert _host_ports(profiled["toxiproxy"]) == {8520, 8521}


def _runtime_stage() -> str:
    """The instructions of the runtime stage of the Dockerfile, continuation lines joined."""
    text = (REPOSITORY / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    return text.split(" AS runtime", 1)[1]


def test_the_image_hands_the_local_data_root_to_its_user() -> None:
    # The pre-deploy campaign of 2026-11-11: compose.yaml mounts a volume under the data root,
    # Docker then made the root as root, and the API (uid 10001) could not write documents.
    stage = _runtime_stage()
    root = re.search(r"VERANICO_DATA_ROOT=(\S+)", stage)
    assert root is not None
    data_root = root[1]
    prepare = re.search(rf"mkdir -p ([^&]*)&& chown -R 10001:10001 {re.escape(data_root)}\b", stage)
    assert prepare is not None, "the runtime stage must create the data root for uid 10001"
    made = prepare[1].split()
    assert f"{data_root}/weather" in made  # the mount point of the weather volume
    assert f"{data_root}/blobs" in made  # the `local` blob store (documents, points)
    assert stage.index(prepare[0]) < stage.index("USER 10001:10001")


@pytest.mark.req("R-7-10")
def test_the_demo_carrier_fails_first_attempts_and_the_campaigns_keep_it_off() -> None:
    compose = yaml.safe_load((REPOSITORY / "compose.yaml").read_text(encoding="utf-8"))
    name = "VERANICO_DELIVERY__CARRIER_FAIL_FIRST_ATTEMPT"

    # By name only: the caller decides, and without it the setting's default (off) applies.
    assert name in compose["services"]["carrier"]["environment"]
    assert f'export {name}="$${{{name}:-true}}"' in _recipe("dev")
    assert f"export {name}=false" in _recipe("test-failure")
    load = (REPOSITORY / "load" / "run.py").read_text(encoding="utf-8")
    assert f'environment["{name}"] = "false"' in load
