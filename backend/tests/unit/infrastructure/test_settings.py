import pytest
from pydantic import ValidationError

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.settings import Settings

API_ROLE_ENVIRONMENT = {
    "VERANICO_COOKIE_SIGNING_SECRET": "cookie-secret",
    "VERANICO_ACCESS__IP_HASH_SALT": "salt",
    "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET": "webhook-secret",
    "VERANICO_DELIVERY__INTERNAL_AUTH": "disabled",
    "VERANICO_ASSISTANT__MODEL_CLIENT": "scripted",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment without any setting."""
    import os

    for name in list(os.environ):
        if name.startswith("VERANICO_") or name in {
            "APP_ROLE",
            "AGENT_MODEL",
            "ANTHROPIC_API_KEY",
            "CDS_API_KEY",
            "FIRESTORE_EMULATOR_HOST",
            "STORAGE_EMULATOR_HOST",
        }:
            monkeypatch.delenv(name)


def _set(monkeypatch: pytest.MonkeyPatch, **variables: str) -> None:
    for name, value in {**API_ROLE_ENVIRONMENT, **variables}.items():
        monkeypatch.setenv(name, value)


def test_loads_prefixed_nested_and_aliased_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        APP_ROLE="api",
        AGENT_MODEL="claude-test-model",
        ANTHROPIC_API_KEY="model-key",
        CDS_API_KEY="cds-key",
        FIRESTORE_EMULATOR_HOST="127.0.0.1:8580",
        STORAGE_EMULATOR_HOST="http://127.0.0.1:8590",
        VERANICO_ENVIRONMENT="test",
        VERANICO_FRAME_ANCESTORS='["http://127.0.0.1:3450"]',
        VERANICO_ACCESS__ALLOWANCE_MESSAGES="7",
        VERANICO_PRICING__RISK_LOAD="0.25",
        VERANICO_DELIVERY__ATTEMPT_LIMIT="3",
        VERANICO_ACCESS__MODEL_PRICES=(
            '{"claude-test-model": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4}}'
        ),
    )

    settings = Settings()

    assert settings.app_role == "api"
    assert settings.agent_model == "claude-test-model"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "model-key"
    assert settings.cds_api_key is not None
    assert settings.firestore_emulator_host == "127.0.0.1:8580"
    assert settings.storage_emulator_host == "http://127.0.0.1:8590"
    assert settings.environment == "test"
    assert settings.frame_ancestors == ["http://127.0.0.1:3450"]
    assert settings.access.allowance_messages == 7
    assert settings.access.allowance_conversations == 2
    assert settings.pricing.risk_load == 0.25
    assert settings.delivery.attempt_limit == 3
    assert settings.access.model_prices["claude-test-model"].cache_write == 4


def test_defaults_are_the_values_of_the_specification(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)

    settings = Settings()

    assert settings.agent_model == "claude-haiku-5-5"
    assert settings.frame_ancestors == []
    assert (settings.access.workspace_ttl_days, settings.access.allowance_conversations) == (14, 2)
    assert (settings.access.allowance_messages, settings.access.boosted_conversations) == (15, 6)
    assert settings.access.boosted_messages == 60
    assert settings.access.day_ceiling_usd_micros == 500_000
    assert settings.access.month_ceiling_usd_micros == 10_000_000
    assert (settings.climate.attempts, settings.climate.first_year) == (4, 1950)
    assert settings.climate.cube_cache_size == 1
    assert (settings.pricing.risk_load, settings.pricing.expense_load) == (0.3, 0.15)
    assert (settings.pricing.simulation_n, settings.pricing.simulation_seed) == (100_000, 42)
    assert settings.pricing.min_seasons == 20
    assert settings.delivery.carrier_fail_first_attempt is False
    assert settings.delivery.timestamp_tolerance_seconds == 300
    assert settings.assistant.tool_call_limit == 10
    assert settings.telemetry.exporter == "none"


def test_default_model_has_integer_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)

    price = Settings().access.model_prices["claude-haiku-5-5"]

    assert price.model_dump() == {
        "input": 100_000,
        "output": 500_000,
        "cache_read": 10_000,
        "cache_write": 125_000,
    }
    assert all(type(value) is int for value in price.model_dump().values())


def test_unknown_app_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, APP_ROLE="worker")

    with pytest.raises(ValidationError, match="APP_ROLE"):
        Settings()


def test_an_empty_variable_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, AGENT_MODEL="", VERANICO_ACCESS__ALLOWANCE_MESSAGES="")

    settings = Settings()

    assert settings.agent_model == "claude-haiku-5-5"
    assert settings.access.allowance_messages == 15


def test_an_empty_secret_does_not_satisfy_a_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, VERANICO_COOKIE_SIGNING_SECRET="")

    with pytest.raises(ValidationError, match="VERANICO_COOKIE_SIGNING_SECRET"):
        Settings()


def test_carrier_role_loads_with_only_its_own_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ROLE", "carrier")
    monkeypatch.setenv("VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET", "webhook-secret")
    monkeypatch.setenv("VERANICO_DELIVERY__CARRIER_FAIL_FIRST_ATTEMPT", "true")
    monkeypatch.setenv("VERANICO_ENVIRONMENT", "production")

    settings = Settings()

    assert settings.app_role == "carrier"
    assert settings.anthropic_api_key is None
    assert settings.cookie_signing_secret is None
    assert settings.access.ip_hash_salt is None
    assert settings.delivery.carrier_fail_first_attempt is True


def test_carrier_role_needs_the_webhook_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ROLE", "carrier")

    with pytest.raises(ValidationError, match="VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET"):
        Settings()


@pytest.mark.parametrize(
    ("removed", "named"),
    [
        ("VERANICO_COOKIE_SIGNING_SECRET", "VERANICO_COOKIE_SIGNING_SECRET"),
        ("VERANICO_ACCESS__IP_HASH_SALT", "VERANICO_ACCESS__IP_HASH_SALT"),
        ("VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET", "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET"),
        ("VERANICO_ASSISTANT__MODEL_CLIENT", "ANTHROPIC_API_KEY"),
        ("VERANICO_DELIVERY__INTERNAL_AUTH", "VERANICO_DELIVERY__OIDC_AUDIENCE"),
    ],
)
def test_api_role_names_the_variable_it_misses(
    monkeypatch: pytest.MonkeyPatch, removed: str, named: str
) -> None:
    _set(monkeypatch)
    monkeypatch.delenv(removed)

    with pytest.raises(ValidationError, match=named):
        Settings()


def test_token_mode_needs_a_token_and_cloud_tasks_needs_a_project() -> None:
    with pytest.raises(ValidationError, match="VERANICO_DELIVERY__INTERNAL_TOKEN"):
        settings_for_tests(delivery={"internal_auth": "token"})
    with pytest.raises(ValidationError, match="VERANICO_DELIVERY__TASKS_PROJECT"):
        settings_for_tests(delivery={"dispatcher": "cloud_tasks"})


@pytest.mark.parametrize("mode", ["disabled", "token"])
def test_internal_routes_without_service_identity_are_refused_in_production(mode: str) -> None:
    with pytest.raises(ValidationError, match="must be oidc in production"):
        settings_for_tests(
            environment="production",
            delivery={"internal_auth": mode, "internal_token": "token"},
        )


def test_oidc_is_accepted_in_production() -> None:
    settings = settings_for_tests(
        environment="production",
        delivery={
            "internal_auth": "oidc",
            "oidc_audience": "https://veranico.example",
            "oidc_invoker_email": "invoker@example.iam.gserviceaccount.com",
        },
    )

    assert settings.delivery.internal_auth == "oidc"


@pytest.mark.parametrize("deadline", [10.0, 9.0])
def test_dispatch_deadline_at_or_below_the_webhook_timeout_is_refused(deadline: float) -> None:
    with pytest.raises(ValidationError, match="must exceed webhook_total_timeout_seconds"):
        settings_for_tests(
            delivery={
                "webhook_total_timeout_seconds": 10.0,
                "tasks_dispatch_deadline_seconds": deadline,
            }
        )


def test_dispatch_deadline_above_the_webhook_timeout_is_accepted() -> None:
    settings = settings_for_tests(
        delivery={"webhook_total_timeout_seconds": 10.0, "tasks_dispatch_deadline_seconds": 10.5}
    )

    assert settings.delivery.tasks_dispatch_deadline_seconds == 10.5


def test_secrets_do_not_appear_in_the_representation() -> None:
    settings = settings_for_tests(anthropic_api_key="model-key-value")

    text = repr(settings) + str(settings.model_dump())

    for secret in ("model-key-value", "test-cookie-signing-secret", "test-ip-hash-salt"):
        assert secret not in text


def test_settings_are_immutable() -> None:
    settings = settings_for_tests()

    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]  # the assignment is the behaviour under test
