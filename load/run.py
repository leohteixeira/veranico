"""`make load`: the load campaign of SPEC 16.5 against a stack of its own on this machine.

    cd backend && uv run python ../load/run.py        # or: make load
    KEEP_STACK=1 make load                             # leave the stack up afterwards

What it does, in order:

1. refuses to start when the load stack already runs: an empty emulator is part of the
   proof, so every run starts its own stack and removes it;
2. builds the schedule (load/fixtures.py) into `.evidence/load/<run_id>/fixtures.json`;
3. starts the emulators, the carrier role and the API as the Compose project
   `veranico-load`, with the per-key rate limit raised above the offered rate. The
   development project `veranico` is never touched;
4. creates one workspace and one API key through the web route;
5. runs k6 from its pinned image on the network of that project, against `http://api:8080`
   and nothing else: the target is not configurable;
6. reads `quoting_quotes` and `quoting_idempotency` from the emulator with a reader of its
   own (the REST interface of the emulator; no code of the service is imported);
7. runs the oracle (load/oracle.py), writes `result.json`, removes the stack.

Exit status: 0 when the oracle has no finding, 1 otherwise, 2 when the run could not be
made at all.

The API key exists only in memory and in the environment of the k6 process. It is never
printed and never written to the run directory.

What a result means, and does not: `LIMITS` below is written into every `result.json`.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fixtures
import oracle

REPOSITORY = Path(__file__).resolve().parents[1]
LOAD = REPOSITORY / "load"
EVIDENCE = REPOSITORY / ".evidence" / "load"

# --- The Compose invocation: the one place that names the project and its files. ---------
PROJECT = "veranico-load"
DEVELOPMENT_PROJECT = "veranico"  # never started, stopped or changed by this script
COMPOSE_FILES = (REPOSITORY / "compose.yaml", LOAD / "compose.load.yaml")  # the second if present
SERVICES = ("firestore", "storage", "carrier", "api")
API_SERVICE, API_PORT = "api", 8080
FIRESTORE_SERVICE, FIRESTORE_PORT = "firestore", 8580
FIRESTORE_PROJECT = os.environ.get("LOAD_FIRESTORE_PROJECT", "veranico-dev")  # the API's default
RATE_SETTING = "VERANICO_ACCESS__API_KEY_RATE_PER_MINUTE"
# 1,000 quote sends from 20 virtual users arrive within seconds. The limit of the run is far
# above that, so the campaign measures idempotency under contention, not the rate limiter.
RATE_PER_MINUTE = 600_000
# compose.yaml hands these to the roles by name; each run makes its own values.
GENERATED_SECRETS = (
    "VERANICO_COOKIE_SIGNING_SECRET",
    "VERANICO_ACCESS__IP_HASH_SALT",
    "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET",
    "VERANICO_DELIVERY__INTERNAL_TOKEN",
)
# Never handed to the load stack, even when the calling shell has them.
WITHHELD_VARIABLES = ("ANTHROPIC_API_KEY", "EARTHENGINE_PROJECT", "AGENT_MODEL")
# ------------------------------------------------------------------------------------------

# k6 v2.3.0; digest resolved with `docker buildx imagetools inspect` on 2026-11-11.
K6_IMAGE = (
    "grafana/k6:2.3.0@sha256:3e4186aea62e11a45560bfc51e19eeafe82fc07ce069c78aff44b7ff893d9a5e"
)
K6_THRESHOLDS_FAILED = 99  # the exit status of k6 when a threshold did not hold
TARGET = f"http://{API_SERVICE}:{API_PORT}"

LIMITS = (
    "The load generator and the service ran on one host and shared its processors.",
    "State was kept in the Firestore emulator, not in Firestore.",
    "The figures show behaviour under contention on this host; they are not a capacity estimate.",
)


class CannotRunError(Exception):
    """The campaign could not be made. Nothing was measured."""


def stack_environment() -> dict[str, str]:
    """The environment Compose is called with: what the roles of this run are given.

    compose.yaml passes these variables to the containers by name. The secrets are random
    values made for this run and kept in memory. The keys of paid or external services are
    removed, whatever the calling shell holds: the campaign calls no model and the stack
    runs on the scripted model client.
    """
    environment = {
        name: value for name, value in os.environ.items() if name not in WITHHELD_VARIABLES
    }
    environment.update({name: secrets.token_hex(32) for name in GENERATED_SECRETS})
    environment["VERANICO_ASSISTANT__MODEL_CLIENT"] = "scripted"
    environment[RATE_SETTING] = str(RATE_PER_MINUTE)
    return environment


_ENVIRONMENT = stack_environment()


def compose(*arguments: str, timeout: int = 600) -> str:
    files = [option for path in COMPOSE_FILES if path.is_file() for option in ("-f", str(path))]
    # `--env-file /dev/null`: Compose reads no `.env` file on its own.
    return _run(
        ["docker", "compose", "--env-file", "/dev/null", "-p", PROJECT, *files, *arguments],
        timeout=timeout,
        environment=_ENVIRONMENT,
    )


def _run(command: list[str], *, timeout: int, environment: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        command,
        cwd=REPOSITORY,
        env=os.environ if environment is None else environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode != 0:
        raise CannotRunError(
            f"`{' '.join(command[:6])} ...` failed:\n{done.stderr.strip()[-2000:]}"
        )
    return done.stdout


def refuse_if_running() -> None:
    if PROJECT == DEVELOPMENT_PROJECT:
        raise CannotRunError("the load project must not be the development project")
    if compose("ps", "--all", "--quiet").strip():
        raise CannotRunError(
            f"the Compose project {PROJECT} already has containers. A run needs an empty "
            f"emulator: remove it with `docker compose -p {PROJECT} down --volumes` first."
        )


def start() -> None:
    # The first run builds the image and seeds the synthetic cubes, which takes minutes.
    compose("up", "--detach", "--build", "--wait", *SERVICES, timeout=1800)


def stop() -> None:
    compose("down", "--volumes", "--remove-orphans", timeout=180)


def network_and_address(service: str) -> tuple[str, str]:
    """The one network of a service's container and the container's address on it."""
    container = compose("ps", "--quiet", service).strip()
    if not container or "\n" in container:
        raise CannotRunError(f"expected exactly one container for the service {service}")
    networks = json.loads(
        _run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
            timeout=30,
        )
    )
    if len(networks) != 1:
        raise CannotRunError(f"the service {service} is on {len(networks)} networks; expected one")
    ((name, settings),) = networks.items()
    return name, settings["IPAddress"]


def require_own_network(network: str) -> None:
    """The run stays inside the load project: its network is not the development one."""
    if network == DEVELOPMENT_PROJECT or not network.startswith(PROJECT):
        raise CannotRunError(
            f"the API of the load stack is on the network {network!r}, which is not a network "
            f"of the project {PROJECT}. The campaign runs only inside its own stack."
        )


def _request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> Any:
    if not url.startswith("http://"):
        raise CannotRunError("only plain HTTP inside the local stack is used")
    request = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def issue_api_key(api: str) -> tuple[str, str]:
    """A new workspace and its API key, through the route the web application uses."""
    issued = _request(f"http://{api}:{API_PORT}/api/v1/workspace/api-keys", method="POST")
    return issued["key_id"], issued["secret"]


class Emulator:
    """Reads documents through the REST interface of the Firestore emulator."""

    def __init__(self, address: str, project: str) -> None:
        self._documents = (
            f"http://{address}:{FIRESTORE_PORT}/v1/projects/{project}/databases/(default)/documents"
        )
        # The emulator treats this bearer value as an administrator; it is not a secret.
        self._headers = {"Authorization": "Bearer owner"}

    def document(self, collection: str, document_id: str) -> dict[str, Any]:
        found = _request(f"{self._documents}/{collection}/{document_id}", headers=self._headers)
        return _fields(found)

    def collection(self, collection: str) -> list[tuple[str, dict[str, Any]]]:
        documents: list[tuple[str, dict[str, Any]]] = []
        token = ""
        while True:
            query = urllib.parse.urlencode({"pageSize": 300, "pageToken": token})
            page = _request(f"{self._documents}/{collection}?{query}", headers=self._headers)
            for found in page.get("documents", []):
                documents.append((found["name"].rsplit("/", 1)[1], _fields(found)))
            token = page.get("nextPageToken", "")
            if not token:
                return documents


def _fields(document: dict[str, Any]) -> dict[str, Any]:
    """The string fields of a REST document; the snapshot needs no other type."""
    return {
        name: value["stringValue"]
        for name, value in document.get("fields", {}).items()
        if "stringValue" in value
    }


def snapshot(emulator: Emulator, key_id: str, schedule: dict[str, Any]) -> dict[str, Any]:
    """Document ids and the key to quote mapping, and nothing else of the documents."""
    workspace_id = emulator.document("access_api_keys", key_id)["workspace_id"]
    keys = sorted({entry["key"] for entry in schedule["quotes"]})
    return {
        "firestore_project": FIRESTORE_PROJECT,
        "workspace_id": workspace_id,
        # `quoting_idempotency/{ref}`: ref is the SHA-256 of "<workspace id>:<key>".
        "key_refs": {
            key: hashlib.sha256(f"{workspace_id}:{key}".encode()).hexdigest() for key in keys
        },
        "quotes": [
            {
                "quote_id": document_id,
                "workspace_id": fields.get("workspace_id"),
                "idempotency_ref": fields.get("idempotency_ref"),
            }
            for document_id, fields in emulator.collection("quoting_quotes")
        ],
        "idempotency": [
            {
                "ref": document_id,
                "workspace_id": fields.get("workspace_id"),
                "quote_id": fields.get("quote_id"),
            }
            for document_id, fields in emulator.collection("quoting_idempotency")
        ],
    }


def run_k6(run_dir: Path, network: str, secret: str) -> int:
    """Run the campaign. Returns the exit status of k6; the key travels in the environment."""
    command = [
        "docker", "run", "--rm",
        "--network", network,
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--volume", f"{LOAD}:/load:ro",
        "--volume", f"{run_dir}:/out",
        "--env", f"BASE_URL={TARGET}",
        "--env", "FIXTURES=/out/fixtures.json",
        "--env", "PROFILE=/load/profile.json",
        "--env", "SUMMARY=/out/k6-summary.json",
        "--env", "API_KEY",  # the value comes from the environment below, not the command line
        K6_IMAGE,
        "run", "--quiet", "--no-usage-report",
        "--console-output", "/out/responses.jsonl", "--log-format", "raw",
        "/load/k6/veranico.js",
    ]  # fmt: skip
    done = subprocess.run(
        command,
        cwd=REPOSITORY,
        env={**os.environ, "API_KEY": secret},
        capture_output=True,
        text=True,
        timeout=1500,
        check=False,
    )
    if done.returncode not in (0, K6_THRESHOLDS_FAILED):
        raise CannotRunError(
            f"k6 ended with status {done.returncode}:\n{done.stderr.strip()[-2000:]}"
        )
    return done.returncode


def identity() -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        done = subprocess.run(
            ["git", *arguments], cwd=REPOSITORY, capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"commit": commit or None, "dirty": status is None or status != ""}


def write_result(
    run_dir: Path, run_id: str, measured_at: datetime, findings: list[oracle.Finding]
) -> dict[str, Any]:
    profile = json.loads(fixtures.PROFILE.read_text(encoding="utf-8"))
    result = {
        "kind": "load",
        "run_id": run_id,
        "identity": identity(),
        "measured_at": measured_at.isoformat(timespec="seconds"),
        "command": "make load",
        "status": "fail" if findings else "pass",
        "summary": {
            **oracle.summarise(run_dir),
            "findings": [str(finding) for finding in findings],
            "profile": profile,
            "rate_limit_per_key_per_minute": RATE_PER_MINUTE,
            "target": TARGET,
            "k6_image": K6_IMAGE,
            "limits": list(LIMITS),
        },
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def campaign(run_dir: Path, run_id: str) -> list[oracle.Finding]:
    profile = json.loads(fixtures.PROFILE.read_text(encoding="utf-8"))
    schedule = fixtures.build(run_id, profile["seed"], profile)
    (run_dir / "fixtures.json").write_text(json.dumps(schedule, indent=1) + "\n", encoding="utf-8")

    start()
    network, api = network_and_address(API_SERVICE)
    require_own_network(network)
    _, firestore = network_and_address(FIRESTORE_SERVICE)
    key_id, secret = issue_api_key(api)

    started = time.monotonic()
    status = run_k6(run_dir, network, secret)
    print(f"k6 finished in {time.monotonic() - started:.0f} s with status {status}")

    emulator = Emulator(firestore, FIRESTORE_PROJECT)
    stored = snapshot(emulator, key_id, schedule)
    (run_dir / "firestore.json").write_text(json.dumps(stored, indent=1) + "\n", encoding="utf-8")
    return oracle.verify(run_dir)


def main() -> int:
    measured_at = datetime.now(UTC)
    run_id = measured_at.strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVIDENCE / run_id
    try:
        refuse_if_running()
        run_dir.mkdir(parents=True)
        try:
            findings = campaign(run_dir, run_id)
        finally:
            if os.environ.get("KEEP_STACK") == "1":
                print(f"KEEP_STACK=1: the project {PROJECT} is left running")
            else:
                stop()
    except (CannotRunError, urllib.error.URLError, subprocess.TimeoutExpired, KeyError) as error:
        print(
            f"load: the campaign could not be made: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 2

    result = write_result(run_dir, run_id, measured_at, findings)
    summary = result["summary"]
    for finding in findings:
        print(f"finding: {finding}")
    print(
        f"load {result['status']}: run {run_id}, {summary['evidence_lines']} of "
        f"{summary['scheduled_requests']} requests evidenced, {summary['keys_acknowledged']} of "
        f"{summary['distinct_keys']} keys acknowledged, {summary['quotes_stored']} quotes stored, "
        f"{len(findings)} findings"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
