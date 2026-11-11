"""Settings for tests: every value a role needs to start, none of them a real secret."""

from typing import Any, Literal

from veranico.shared.infrastructure.settings import Settings

# Values the settings require on the API role. They are fixed test strings, not secrets.
_API_ROLE: dict[str, Any] = {
    "environment": "test",
    "cookie_signing_secret": "test-cookie-signing-secret",
    "access": {"ip_hash_salt": "test-ip-hash-salt", "allowance_code": "test-allowance-code"},
    "delivery": {
        "webhook_signing_secret": "test-webhook-signing-secret",
        "internal_auth": "disabled",
    },
    "assistant": {"model_client": "scripted"},
}
_CARRIER_ROLE: dict[str, Any] = {
    "environment": "test",
    "delivery": {"webhook_signing_secret": "test-webhook-signing-secret"},
}


def settings_for_tests(role: Literal["api", "carrier"] = "api", **overrides: Any) -> Settings:
    """Build valid settings for a role.

    An override replaces a top-level value; an override of a group (`access`, `climate`,
    `pricing`, `delivery`, `assistant`, `telemetry`) is a mapping merged over the test
    values of that group, for example `settings_for_tests(pricing={"min_seasons": 3})`.
    """
    values: dict[str, Any] = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in (_API_ROLE if role == "api" else _CARRIER_ROLE).items()
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(values.get(key), dict):
            values[key] = {**values[key], **value}
        else:
            values[key] = value
    return Settings(app_role=role, **values)
