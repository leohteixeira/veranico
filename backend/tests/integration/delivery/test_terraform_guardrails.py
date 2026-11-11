"""The Terraform guardrails of SPEC 17, run from pytest so they enter the traceability matrix.

The assertions themselves live in `infra/terraform/tests/guardrails.tftest.hcl` and run with
`terraform test`: the provider is mocked and every run only plans, so no Google project, no
credentials and no state are involved. This wrapper adds nothing but the exit status.

    uv run pytest tests/integration/delivery/test_terraform_guardrails.py -m external -q

The provider is downloaded by `terraform init -backend=false` on first use, which needs the
network once.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.external

TERRAFORM_DIR = Path(__file__).resolve().parents[4] / "infra" / "terraform"

GUARDRAIL_RUNS = (
    "services_scale_from_zero_to_two",
    "no_domain_is_mapped_unless_one_is_given",
    "a_given_domain_is_mapped_to_the_api_service",
    "every_regional_resource_is_in_us_central1",
    "another_region_is_rejected",
    "bucket_is_private",
    "every_expiring_collection_has_a_ttl_policy",
    "registry_keeps_the_last_three_images",
    "federation_is_restricted_to_one_repository",
    "federation_also_requires_the_repository_id_when_given",
    "deployer_has_no_primitive_role",
    "five_secrets_and_each_role_reads_only_its_own",
    "cds_key_never_reaches_a_service",
    "uptime_check_and_budget_exist",
    "queue_and_application_share_their_limits",
    "internal_callers_use_the_identity_the_service_checks",
    "dispatch_deadline_must_exceed_the_webhook_timeout",
)


def _terraform(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["terraform", f"-chdir={TERRAFORM_DIR}", *arguments, "-no-color"],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


@pytest.fixture(scope="module")
def initialised() -> None:
    if shutil.which("terraform") is None:
        pytest.fail("terraform is not installed: the guardrails cannot be checked")
    result = _terraform("init", "-backend=false", "-input=false")
    if result.returncode != 0:
        pytest.fail(f"terraform init -backend=false failed:\n{result.stdout}\n{result.stderr}")


@pytest.mark.req("R-17-2")
@pytest.mark.usefixtures("initialised")
def test_the_configuration_is_formatted_and_valid() -> None:
    formatted = _terraform("fmt", "-check", "-recursive")
    assert formatted.returncode == 0, f"terraform fmt -check:\n{formatted.stdout}"

    valid = _terraform("validate")
    assert valid.returncode == 0, f"{valid.stdout}\n{valid.stderr}"


@pytest.fixture(scope="module")
def guardrails(initialised: None) -> subprocess.CompletedProcess[str]:
    """One `terraform test` for the module: its exit status and the list of runs."""
    return _terraform("test")


@pytest.mark.req("R-17-3", "R-17-5", "R-15-6")
def test_every_guardrail_run_passes(guardrails: subprocess.CompletedProcess[str]) -> None:
    assert guardrails.returncode == 0, f"{guardrails.stdout}\n{guardrails.stderr}"
    # A run that was renamed or removed must not go unnoticed behind a green exit status.
    for run in GUARDRAIL_RUNS:
        assert f'run "{run}"... pass' in guardrails.stdout, f"guardrail run missing: {run}"


@pytest.mark.req("R-17-4")
def test_the_address_is_the_cloud_run_url_and_a_domain_is_optional(
    guardrails: subprocess.CompletedProcess[str],
) -> None:
    """The product's address is the service's own URL; a domain is mapped only when given."""
    outputs = (TERRAFORM_DIR / "outputs.tf").read_text(encoding="utf-8")
    api_url = outputs.split('output "api_url"')[1].split("}")[0]
    assert "google_cloud_run_v2_service.api.uri" in api_url

    for run in (
        "no_domain_is_mapped_unless_one_is_given",
        "a_given_domain_is_mapped_to_the_api_service",
    ):
        assert f'run "{run}"... pass' in guardrails.stdout, guardrails.stdout
