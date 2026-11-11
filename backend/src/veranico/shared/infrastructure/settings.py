"""Application settings, read from environment variables.

Variables use the prefix `VERANICO_` and `__` between a group and a field
(`VERANICO_ACCESS__ALLOWANCE_MESSAGES`). The names the specification and the SDKs fix stay
unprefixed: `APP_ROLE`, `AGENT_MODEL`, `ANTHROPIC_API_KEY`, `CDS_API_KEY`,
`FIRESTORE_EMULATOR_HOST` and `STORAGE_EMULATOR_HOST`. pydantic-settings reads an unprefixed
variable only into a top-level field, so these six are fields of `Settings` itself and not
of the group they belong to. `env.example` at the repository root lists every variable.

A variable set to an empty string counts as unset. Lists and objects are JSON
(`VERANICO_FRAME_ANCESTORS=["http://127.0.0.1:3450"]`).

A value is required only on the role that uses it: the carrier role starts with the webhook
signing secret alone, and needs neither the model key nor any other module's secret.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AGENT_MODEL = "claude-haiku-5-5"


class ModelPrice(BaseModel, frozen=True):
    """Prices of one model in integer micro-dollars per million tokens.

    Micro-dollars per million tokens are also pico-dollars per token, so a cost in
    micro-dollars is `tokens * price // 1_000_000` and needs no float.
    """

    input: int = Field(ge=0)
    output: int = Field(ge=0)
    cache_read: int = Field(ge=0)
    cache_write: int = Field(ge=0)


class AccessSettings(BaseModel, frozen=True):
    workspace_ttl_days: int = Field(default=14, gt=0)
    allowance_conversations: int = Field(default=2, ge=0)
    allowance_messages: int = Field(default=15, ge=0)
    boosted_conversations: int = Field(default=6, ge=0)
    boosted_messages: int = Field(default=60, ge=0)
    allowance_code: SecretStr | None = None
    ip_hash_salt: SecretStr | None = None
    day_ceiling_usd_micros: int = Field(default=500_000, ge=0)  # US$ 0.50
    month_ceiling_usd_micros: int = Field(default=10_000_000, ge=0)  # US$ 10
    # Claude Haiku 5.5, prompts of up to 100,000 tokens; cache write is the 5-minute price.
    # Source: https://platform.claude.com/docs/en/about-claude/pricing, read on 2026-11-10
    # (US$ 0.10 input, 0.50 output, 0.01 cache read, 0.125 cache write per million tokens).
    # A prompt over 100,000 tokens is billed at five times these prices, which this table
    # does not model: the compaction threshold keeps prompts below that size.
    model_prices: dict[str, ModelPrice] = {
        DEFAULT_AGENT_MODEL: ModelPrice(
            input=100_000, output=500_000, cache_read=10_000, cache_write=125_000
        )
    }
    api_key_rate_per_minute: int = Field(default=60, gt=0)
    max_message_chars: int = Field(default=2_000, gt=0)
    conversation_token_budget: int = Field(default=200_000, gt=0)


class ClimateSettings(BaseModel, frozen=True):
    store_backend: Literal["local", "gcs"] = "local"
    store_root: Path = Path(".data/weather")
    archive_base_url: str = "https://archive-api.open-meteo.com"
    geocoding_base_url: str = "https://geocoding-api.open-meteo.com"
    attempt_timeout_seconds: float = Field(default=10.0, gt=0)
    attempts: int = Field(default=4, gt=0)
    backoff_base_seconds: float = Field(default=0.5, gt=0)
    first_year: int = 1950
    # Decoded cubes kept in memory, about 89 MB each. The default keeps the three showcase
    # regions: with fewer, requests that alternate between regions decode a cube each time.
    cube_cache_size: int = Field(default=3, gt=0)


class PricingSettings(BaseModel, frozen=True):
    risk_load: float = Field(default=0.3, ge=0)
    expense_load: float = Field(default=0.15, ge=0)
    simulation_n: int = Field(default=100_000, gt=0)
    simulation_seed: int = 42
    min_seasons: int = Field(default=20, gt=0)
    cell_cache_entries: int = Field(default=64, gt=0)


class DeliverySettings(BaseModel, frozen=True):
    """Webhook delivery: shared by `quoting` (outbox, dispatcher, sweep) and `carriers`."""

    webhook_signing_secret: SecretStr | None = None
    carrier_base_url: str = "http://127.0.0.1:8510"
    webhook_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    webhook_total_timeout_seconds: float = Field(default=10.0, gt=0)
    dispatcher: Literal["relay", "cloud_tasks"] = "relay"
    attempt_limit: int = Field(default=5, gt=0)  # webhook attempts of one delivery round
    # The queue's whole retry window: the sweep abandons a delivery silent for longer.
    retry_window_seconds: int = Field(default=3_600, gt=0)
    relay_poll_interval_seconds: float = Field(default=1.0, gt=0)
    relay_backoff_base_seconds: float = Field(default=1.0, gt=0)
    relay_backoff_cap_seconds: float = Field(default=30.0, gt=0)
    sweep_age_seconds: int = Field(default=60, ge=0)
    # The service's own address for the relay, the public service URL for Cloud Tasks.
    internal_base_url: str = "http://127.0.0.1:8500"
    internal_auth: Literal["disabled", "token", "oidc"] = "oidc"
    internal_token: SecretStr | None = None  # development only
    oidc_audience: str | None = None
    oidc_invoker_email: str | None = None
    tasks_project: str | None = None
    tasks_location: str = "us-central1"
    tasks_queue: str = "veranico-deliveries"
    tasks_dispatch_deadline_seconds: float = Field(default=30.0, gt=0)
    carrier_fail_first_attempt: bool = False
    timestamp_tolerance_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def _deadline_exceeds_webhook_timeout(self) -> Self:
        if self.tasks_dispatch_deadline_seconds <= self.webhook_total_timeout_seconds:
            raise ValueError(
                "tasks_dispatch_deadline_seconds must exceed webhook_total_timeout_seconds: "
                "the queue would cancel a call before its attempt is recorded"
            )
        return self


class AssistantSettings(BaseModel, frozen=True):
    model_client: Literal["anthropic", "scripted"] = "anthropic"
    tool_call_limit: int = Field(default=10, gt=0)
    # Set by the assistant plan for Claude Haiku 5.5: the estimate of three characters per
    # token errs toward compacting early, and the threshold stays under the 100K price step.
    max_output_tokens: int = Field(default=4_096, gt=0)
    model_timeout_seconds: float = Field(default=60.0, gt=0)
    compaction_threshold_tokens: int = Field(default=60_000, gt=0)
    chars_per_token: int = Field(default=3, gt=0)


class TelemetrySettings(BaseModel, frozen=True):
    exporter: Literal["none", "otlp", "cloud_trace"] = "none"
    otlp_endpoint: str | None = None
    service_name: str = "veranico"
    service_version: str = "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERANICO_",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
        validate_by_name=True,
        validate_by_alias=True,
    )

    # Unprefixed names fixed by the specification and the SDKs.
    app_role: Literal["api", "carrier"] = Field(default="api", alias="APP_ROLE")
    agent_model: str = Field(default=DEFAULT_AGENT_MODEL, alias="AGENT_MODEL")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    # Offline cube build only; never needed by the running service.
    cds_api_key: SecretStr | None = Field(default=None, alias="CDS_API_KEY")
    # `host:port`, no scheme. The Firestore SDK reads the variable itself; see firestore.py.
    firestore_emulator_host: str | None = Field(default=None, alias="FIRESTORE_EMULATOR_HOST")
    # With the scheme: `http://host:port`.
    storage_emulator_host: str | None = Field(default=None, alias="STORAGE_EMULATOR_HOST")

    # Core.
    environment: Literal["development", "test", "production"] = "development"
    firestore_project: str = "veranico-dev"
    storage_bucket: str = "veranico-dev"
    blob_backend: Literal["local", "gcs"] = "local"
    data_root: Path = Path(".data")
    cookie_signing_secret: SecretStr | None = None
    # Origins allowed to frame /embed/map. Empty: no page may frame it.
    frame_ancestors: list[str] = []
    # The built frontend, served at the root on the API role when the directory exists.
    frontend_dist: Path = Path("../frontend/dist")

    access: AccessSettings = AccessSettings()
    climate: ClimateSettings = ClimateSettings()
    pricing: PricingSettings = PricingSettings()
    delivery: DeliverySettings = DeliverySettings()
    assistant: AssistantSettings = AssistantSettings()
    telemetry: TelemetrySettings = TelemetrySettings()

    @model_validator(mode="after")
    def _role_has_what_it_uses(self) -> Self:
        missing: list[str] = []

        def require(value: object, variable: str) -> None:
            if value is None:
                missing.append(variable)

        require(self.delivery.webhook_signing_secret, "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET")
        if self.app_role == "api":
            delivery = self.delivery
            require(self.cookie_signing_secret, "VERANICO_COOKIE_SIGNING_SECRET")
            require(self.access.ip_hash_salt, "VERANICO_ACCESS__IP_HASH_SALT")
            if delivery.internal_auth == "token":
                require(delivery.internal_token, "VERANICO_DELIVERY__INTERNAL_TOKEN")
            if delivery.internal_auth == "oidc":
                require(delivery.oidc_audience, "VERANICO_DELIVERY__OIDC_AUDIENCE")
                require(delivery.oidc_invoker_email, "VERANICO_DELIVERY__OIDC_INVOKER_EMAIL")
            if delivery.dispatcher == "cloud_tasks":
                require(delivery.tasks_project, "VERANICO_DELIVERY__TASKS_PROJECT")
            if self.assistant.model_client == "anthropic":
                require(self.anthropic_api_key, "ANTHROPIC_API_KEY")
        if missing:
            raise ValueError(f"APP_ROLE={self.app_role} needs: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _production_authenticates_internal_calls(self) -> Self:
        if self.environment == "production" and self.delivery.internal_auth != "oidc":
            raise ValueError(
                "VERANICO_DELIVERY__INTERNAL_AUTH must be oidc in production: "
                f"{self.delivery.internal_auth} gives the internal routes no service identity"
            )
        return self
