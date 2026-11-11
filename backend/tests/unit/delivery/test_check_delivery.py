"""`.github/scripts/check_delivery.py`: one violating snippet per rule, and the real files."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / ".github" / "scripts" / "check_delivery.py"

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
DIGEST = "sha256:" + "ab" * 32

GOOD = f"""\
name: Example
on:
  push:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
      - run: make lint
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_delivery", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load()


def _changed(old: str, new: str) -> str:
    assert old in GOOD
    return GOOD.replace(old, new)


def test_a_pinned_read_only_workflow_has_no_finding() -> None:
    assert checker.check_workflow("example.yml", GOOD) == []


VIOLATIONS = {
    "an action pinned by tag": (
        _changed(f"actions/checkout@{SHA} # v7.0.1", "actions/checkout@v7"),
        "not pinned to a 40-hex commit",
    ),
    "an action pinned by a short commit": (
        _changed(f"actions/checkout@{SHA} # v7.0.1", f"actions/checkout@{SHA[:12]} # v7.0.1"),
        "not pinned to a 40-hex commit",
    ),
    "a pinned action without its tag comment": (
        _changed(f"@{SHA} # v7.0.1", f"@{SHA}"),
        "without a '# <tag>' comment",
    ),
    "a docker action without a digest": (
        _changed("- run: make lint", "- uses: docker://ghcr.io/example/tool:1.2.3"),
        "docker action without a @sha256 digest",
    ),
    "a job container without a digest": (
        _changed("    steps:", "    container: python:3.12\n    steps:"),
        "container image without a @sha256 digest",
    ),
    "a service image without a digest": (
        _changed("    steps:", "    services:\n      db:\n        image: postgres:18\n    steps:"),
        "service db image without a @sha256 digest",
    ),
    "an image variable without a digest": (
        _changed(
            "    steps:", "    env:\n      TOOL_IMAGE: ghcr.io/example/tool:1.2.3\n    steps:"
        ),
        "image variable TOOL_IMAGE without a @sha256 digest",
    ),
    "a docker run of a tag": (
        _changed("- run: make lint", "- run: docker run --rm ghcr.io/example/tool:1.2.3 scan"),
        "docker run or pull of an image without a @sha256 digest",
    ),
    "write permissions at the top": (
        _changed("permissions:\n  contents: read", "permissions:\n  contents: write"),
        "top-level permissions must be exactly 'contents: read'",
    ),
    "an extra permission at the top": (
        _changed("  contents: read", "  contents: read\n  id-token: write"),
        "top-level permissions must be exactly 'contents: read'",
    ),
    "no permissions at the top": (
        _changed("permissions:\n  contents: read\n", ""),
        "top-level permissions must be exactly 'contents: read'",
    ),
    "a job permission outside the allow list": (
        _changed("    steps:", "    permissions:\n      id-token: write\n    steps:"),
        "job build: permissions {'id-token': 'write'} are not in the allow list",
    ),
    "the pull_request_target trigger": (
        _changed("  push:", "  pull_request_target:"),
        "pull_request_target is not allowed",
    ),
    "a JSON credential input": (
        _changed(
            "- run: make lint", "- run: make lint\n        with:\n          credentials_json: x"
        ),
        "credentials_json is not allowed",
    ),
    "a key file": (
        _changed("make lint", "gcloud auth activate-service-account --key-file=key.json"),
        "--key-file is not allowed",
    ),
    "a credentials variable": (
        _changed(
            "- run: make lint", "- run: make lint\n        env:\n          GOOGLE_CREDENTIALS: x"
        ),
        "GOOGLE_CREDENTIALS is not allowed",
    ),
}


@pytest.mark.parametrize("case", sorted(VIOLATIONS))
def test_each_violation_is_reported(case: str) -> None:
    text, expected = VIOLATIONS[case]

    findings = checker.check_workflow("example.yml", text)

    assert any(expected in finding for finding in findings), findings
    assert all(finding.startswith("example.yml") for finding in findings)


def test_a_digest_pinned_image_is_accepted_everywhere() -> None:
    text = _changed(
        "    steps:",
        f"    container: python:3.12@{DIGEST}\n"
        f"    env:\n      TOOL_IMAGE: ghcr.io/example/tool:1.2.3@{DIGEST}\n"
        "    steps:\n"
        '      - run: docker run --rm "$TOOL_IMAGE" scan\n'
        f"      - uses: docker://ghcr.io/example/tool:1.2.3@{DIGEST}",
    )

    assert checker.check_workflow("example.yml", text) == []


def test_a_forbidden_word_in_a_comment_is_not_a_finding() -> None:
    text = "# pull_request_target is never used here.\n" + GOOD

    assert checker.check_workflow("example.yml", text) == []


def test_the_deploy_job_alone_may_request_the_identity_token() -> None:
    text = _changed(
        "    steps:", "    permissions:\n      contents: read\n      id-token: write\n    steps:"
    ).replace("  build:", "  deploy:")

    assert checker.check_workflow("deploy.yml", text) == []
    assert checker.check_workflow("ci.yml", text) != []


def test_the_load_workflow_takes_no_input_and_no_other_trigger() -> None:
    manual = _changed("  push:", "  workflow_dispatch:")
    with_input = _changed(
        "  push:",
        "  workflow_dispatch:\n    inputs:\n      target:\n        type: string",
    )

    assert checker.check_workflow("load.yml", manual) == []
    assert "load.yml: workflow_dispatch must take no input" in checker.check_workflow(
        "load.yml", with_input
    )
    assert "load.yml: the only trigger must be workflow_dispatch" in checker.check_workflow(
        "load.yml", GOOD
    )


def test_a_missing_required_workflow_is_reported(tmp_path: Path) -> None:
    (tmp_path / "ci.yml").write_text(GOOD, encoding="utf-8")

    findings = checker.check_workflows(tmp_path)

    assert findings == [
        "evals.yml: required workflow is missing",
        "load.yml: required workflow is missing",
        "deploy.yml: required workflow is missing",
    ]


def test_a_service_account_key_resource_is_reported(tmp_path: Path) -> None:
    (tmp_path / "iam.tf").write_text(
        'resource "google_service_account" "api" {}\n'
        'resource "google_service_account_key" "api" {}\n',
        encoding="utf-8",
    )
    cached = tmp_path / ".terraform" / "modules"
    cached.mkdir(parents=True)
    (cached / "x.tf").write_text('resource "google_service_account_key" "x" {}\n', encoding="utf-8")

    findings = checker.check_terraform_keys(tmp_path)

    assert findings == ["iam.tf:2: service account key resource; use Workload Identity Federation"]


def test_an_empty_terraform_directory_is_a_finding(tmp_path: Path) -> None:
    assert checker.check_terraform_keys(tmp_path) != []


@pytest.mark.req("R-16.9-6")
def test_the_real_workflows_and_terraform_pass() -> None:
    assert checker.check_workflows() == []
    assert checker.check_terraform_keys() == []


def test_the_exit_status_follows_the_findings(capsys: pytest.CaptureFixture[str]) -> None:
    assert checker.main(["workflows"]) == 0
    assert checker.main(["terraform-keys"]) == 0
    assert checker.main(["readme"]) == 0
    assert checker.main(["unknown"]) == 2
    assert checker.main([]) == 2
    assert "usage" in capsys.readouterr().out


def _readme(**changes: str) -> str:
    """A README with the twelve sections; `changes` replaces the body of a section."""
    bodies = {str(number): f"Text of section {number}." for number in range(1, 12)}
    bodies["12"] = checker.README_PLACEHOLDER
    bodies.update(changes)
    sections = [f"## {number}. Title {number}\n\n{body}\n" for number, body in bodies.items()]
    return "# Project\n\n> A note near the top.\n\n" + "\n".join(sections)


def test_a_readme_with_the_twelve_sections_and_the_placeholder_passes(tmp_path: Path) -> None:
    assert checker.check_readme_text(_readme(), tmp_path) == []


def test_the_real_readme_passes() -> None:
    assert checker.check_readme() == []


def test_a_missing_or_misordered_section_is_reported(tmp_path: Path) -> None:
    without_seven = _readme().replace("## 7. Title 7", "### 7. Title 7")
    swapped = _readme().replace("## 3. Title 3", "## 4. Title 3", 1)

    assert "in order" in checker.check_readme_text(without_seven, tmp_path)[0]
    assert "in order" in checker.check_readme_text(swapped, tmp_path)[0]


def test_an_empty_section_is_reported(tmp_path: Path) -> None:
    assert checker.check_readme_text(_readme(**{"5": ""}), tmp_path) == [
        "README.md: section 5 is empty"
    ]


@pytest.mark.parametrize(
    "body",
    [
        "",
        "I would change the cache.",
        checker.README_PLACEHOLDER + "\n\nAnd I would also change the cache.",
    ],
)
def test_section_twelve_holds_only_the_placeholder_of_the_author(body: str, tmp_path: Path) -> None:
    assert checker.check_readme_text(_readme(**{"12": body}), tmp_path) == [
        "README.md: section 12 must hold only the author's placeholder"
    ]


def test_a_relative_link_must_resolve_and_an_external_one_is_not_followed(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "there.md").write_text("x", encoding="utf-8")
    body = "[a](docs/there.md#part) [b](docs/missing.md) [c](https://example.com/x) [d](#top)"

    assert checker.check_readme_text(_readme(**{"2": body}), tmp_path) == [
        "README.md: the link docs/missing.md resolves to no file"
    ]


def test_a_missing_readme_is_a_finding(tmp_path: Path) -> None:
    assert checker.check_readme(tmp_path / "README.md") == ["README.md: missing"]
