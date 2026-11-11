"""Static delivery checks that need no network and no credentials.

    cd backend && uv run python ../.github/scripts/check_delivery.py workflows
    cd backend && uv run python ../.github/scripts/check_delivery.py terraform-keys
    cd backend && uv run python ../.github/scripts/check_delivery.py readme

Each command prints one line per finding and exits 1 when there is any, 0 otherwise.

`workflows` reads `.github/workflows/*.yml`:

- every `uses:` names a full 40-hex commit followed by a `# <tag>` comment (a local `./`
  action needs no pin; a `docker://` action needs a digest);
- every container image (`image:`, a job `container:`, an `*_IMAGE` variable, a
  `docker run` line) carries a `@sha256:` digest;
- top-level `permissions` is exactly `contents: read`;
- a job-level `permissions` block is `contents: read` or the entry of the allow list below;
- no `pull_request_target` trigger, no JSON credential input and no key file;
- the load workflow takes no input, so it cannot be pointed at another address;
- the four workflows exist.

`terraform-keys` reads `infra/terraform/**/*.tf`: no service account key resource.

`readme` reads `README.md`: the twelve sections of SPEC 19 exist as `## <n>. <title>`
headings in order; sections 1 to 11 are not empty; section 12 holds only the author's
placeholder, because that section is written by the author and never generated; and every
relative link resolves to a file of the repository.
"""

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

REPOSITORY = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY / ".github" / "workflows"
TERRAFORM = REPOSITORY / "infra" / "terraform"

REQUIRED_WORKFLOWS = ("ci.yml", "evals.yml", "load.yml", "deploy.yml")
NO_INPUT_WORKFLOWS = ("load.yml",)

READ_ONLY = {"contents": "read"}
# (workflow, job) -> the only permissions that job may declare besides the read-only default.
ALLOWED_JOB_PERMISSIONS: dict[tuple[str, str], dict[str, str]] = {
    ("deploy.yml", "deploy"): {"contents": "read", "id-token": "write"},
}

FORBIDDEN_TEXT = {
    "pull_request_target": "the pull_request_target trigger runs fork code with secrets",
    "credentials_json": "a JSON credential input means a service account key",
    "--key-file": "a key file means a service account key",
    "activate-service-account": "activating a service account means a key file",
    "GOOGLE_CREDENTIALS": "a credentials variable means a service account key",
    "GOOGLE_APPLICATION_CREDENTIALS": "a credentials file means a service account key",
}

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<target>\S+)(?P<rest>.*)$")
_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_TAG_COMMENT = re.compile(r"^\s+#\s*v?\d\S*\s*$")
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")
_IMAGE_VARIABLE = re.compile(r"^\s*(?P<name>[A-Z0-9_]*IMAGE):\s*(?P<value>\S.*)$")
_IMAGE_REFERENCE = re.compile(r"\$\{?[A-Z0-9_]*IMAGE\}?")
_KEY_RESOURCE = re.compile(r'^\s*resource\s+"google_service_account_key"')

README = REPOSITORY / "README.md"
README_SECTIONS = 12  # SPEC 19
# Section 12 ("What I would change") is the author's. Until it is written it holds this
# line and nothing else; once the author writes it, this check is changed with it.
README_PLACEHOLDER = "_Written by the author after the build (human gate H3). Not generated._"
_SECTION_HEADING = re.compile(r"^## (\d+)\. \S.*$", re.MULTILINE)
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _without_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    return line.split(" #", 1)[0]


def _line_findings(name: str, text: str) -> list[str]:
    findings: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        where = f"{name}:{number}"
        line = _without_comment(raw)
        if not line.strip():
            continue

        uses = _USES.match(raw)
        if uses:
            target = uses["target"].strip("\"'")
            if target.startswith("./"):
                pass
            elif target.startswith("docker://"):
                if not _DIGEST.search(target):
                    findings.append(f"{where}: docker action without a @sha256 digest: {target}")
            elif not _PINNED.match(target):
                findings.append(f"{where}: action not pinned to a 40-hex commit: {target}")
            elif not _TAG_COMMENT.match(uses["rest"]):
                findings.append(f"{where}: pinned action without a '# <tag>' comment: {target}")

        variable = _IMAGE_VARIABLE.match(line)
        if variable and not _DIGEST.search(variable["value"]):
            findings.append(f"{where}: image variable {variable['name']} without a @sha256 digest")

        if (
            re.search(r"\bdocker\s+(run|pull)\b", line)
            and not _DIGEST.search(line)
            and not _IMAGE_REFERENCE.search(line)
        ):
            findings.append(f"{where}: docker run or pull of an image without a @sha256 digest")

        for needle, reason in FORBIDDEN_TEXT.items():
            if needle in line:
                findings.append(f"{where}: {needle} is not allowed: {reason}")
    return findings


def _image_findings(name: str, job_name: str, job: Mapping[str, Any]) -> list[str]:
    images: list[tuple[str, object]] = []
    container = job.get("container")
    if isinstance(container, Mapping):
        images.append(("container", container.get("image")))
    elif container is not None:
        images.append(("container", container))
    services = job.get("services")
    if isinstance(services, Mapping):
        for service_name, service in services.items():
            image = service.get("image") if isinstance(service, Mapping) else None
            images.append((f"service {service_name}", image))
    return [
        f"{name}: job {job_name}: {label} image without a @sha256 digest: {image}"
        for label, image in images
        if not (isinstance(image, str) and _DIGEST.search(image))
    ]


def check_workflow(name: str, text: str) -> list[str]:
    """Return the findings of one workflow file, given its name and its text."""
    findings = _line_findings(name, text)
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [*findings, f"{name}: not valid YAML: {type(error).__name__}"]
    if not isinstance(document, Mapping):
        return [*findings, f"{name}: not a workflow document"]

    if document.get("permissions") != READ_ONLY:
        findings.append(f"{name}: top-level permissions must be exactly 'contents: read'")

    # YAML 1.1 reads the bare key `on` as the boolean true.
    triggers = document.get("on", document.get(True))
    if name in NO_INPUT_WORKFLOWS:
        if not isinstance(triggers, Mapping) or set(triggers) != {"workflow_dispatch"}:
            findings.append(f"{name}: the only trigger must be workflow_dispatch")
        elif triggers["workflow_dispatch"]:
            findings.append(f"{name}: workflow_dispatch must take no input")

    jobs = document.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        return [*findings, f"{name}: no jobs"]
    for job_name, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        findings.extend(_image_findings(name, str(job_name), job))
        if "permissions" not in job:
            continue
        allowed = (READ_ONLY, ALLOWED_JOB_PERMISSIONS.get((name, str(job_name))))
        if job["permissions"] not in allowed:
            declared = job["permissions"]
            findings.append(
                f"{name}: job {job_name}: permissions {declared} are not in the allow list"
            )
    return findings


def check_workflows(directory: Path = WORKFLOWS) -> list[str]:
    findings = [
        f"{name}: required workflow is missing"
        for name in REQUIRED_WORKFLOWS
        if not (directory / name).is_file()
    ]
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        findings.extend(check_workflow(path.name, path.read_text(encoding="utf-8")))
    return findings


def check_terraform_text(name: str, text: str) -> list[str]:
    return [
        f"{name}:{number}: service account key resource; use Workload Identity Federation"
        for number, line in enumerate(text.splitlines(), start=1)
        if _KEY_RESOURCE.match(line)
    ]


def check_terraform_keys(directory: Path = TERRAFORM) -> list[str]:
    findings: list[str] = []
    files = [path for path in sorted(directory.rglob("*.tf")) if ".terraform" not in path.parts]
    if not files:
        return [f"{directory.name}: no Terraform file found"]
    for path in files:
        relative = path.relative_to(directory).as_posix()
        findings.extend(check_terraform_text(relative, path.read_text(encoding="utf-8")))
    return findings


def check_readme_text(text: str, root: Path = REPOSITORY) -> list[str]:
    findings: list[str] = []
    headings = [
        (int(found[1]), found.start(), found.end()) for found in _SECTION_HEADING.finditer(text)
    ]
    numbers = [number for number, _, _ in headings]
    if numbers != list(range(1, README_SECTIONS + 1)):
        return [
            f"README.md: sections must be '## 1.' to '## {README_SECTIONS}.' in order: {numbers}"
        ]
    for position, (number, _, end) in enumerate(headings):
        following = headings[position + 1][1] if position + 1 < len(headings) else len(text)
        body = text[end:following].strip()
        if number < README_SECTIONS and not body:
            findings.append(f"README.md: section {number} is empty")
        if number == README_SECTIONS and body != README_PLACEHOLDER:
            findings.append(
                f"README.md: section {README_SECTIONS} must hold only the author's placeholder"
            )
    for target in sorted({found[1] for found in _LINK.finditer(text)}):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        if not (root / target.split("#", 1)[0]).exists():
            findings.append(f"README.md: the link {target} resolves to no file")
    return findings


def check_readme(path: Path = README) -> list[str]:
    if not path.is_file():
        return ["README.md: missing"]
    return check_readme_text(path.read_text(encoding="utf-8"), path.parent)


def main(arguments: list[str]) -> int:
    commands = {
        "workflows": check_workflows,
        "terraform-keys": check_terraform_keys,
        "readme": check_readme,
    }
    if len(arguments) != 1 or arguments[0] not in commands:
        print("usage: check_delivery.py workflows | terraform-keys | readme")
        return 2
    findings = commands[arguments[0]]()
    for finding in findings:
        print(finding)
    if findings:
        return 1
    print(f"{arguments[0]}: no finding")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
