"""Runtime configuration. Every value comes from the environment (prefix ARBITER_).

Nothing secret has a default. Provider keys are optional: when a key is missing the
provider is reported as unavailable and the router skips it. The mock provider is
always available and is the default in dev and test.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARBITER_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    database_url: str = "postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter"
    storage_dir: str = "./var/storage"
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"  # comma separated

    # Seller (for invoices). Tax treatment needs legal/tax review before public launch.
    seller_country: str = ""
    vat_rate: str = "0"

    # Auth
    jwt_secret: str = Field(default="dev-only-change-me-not-for-production-use", min_length=32)
    jwt_ttl_minutes: int = 60 * 12

    # Providers. Empty string = not configured.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    deepl_api_key: str = ""
    google_api_key: str = ""
    embedding_provider: Literal["mock", "openai"] = "mock"

    # EU processing route (D-052). Bedrock: AWS keys for the platform account; model is an
    # EU geographic inference profile id, which routes only among EU regions.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    bedrock_region: str = "eu-central-1"
    bedrock_model: str = "eu.anthropic.claude-opus-5"
    # Claude on Vertex AI: service account JSON (whole file content), project and location.
    vertex_service_account_json: str = ""
    vertex_project: str = ""
    vertex_location: str = "eu"
    vertex_model: str = "claude-opus-5"

    # Fine-tuning providers for own models (arbiter.training).
    together_api_key: str = ""
    fireworks_api_key: str = ""
    fireworks_account_id: str = ""

    # Engine credentials stored in the database are encrypted with this key (Fernet).
    # Comma separated for rotation: the first key encrypts, every key decrypts.
    # Required in prod; dev and test fall back to a fixed dev-only key.
    secrets_key: str = ""

    # Engines used when no scoreboard data exists for a pair (R-MT-02).
    default_mt_engine: str = "mock-mt"
    default_judge_engine: str = "mock-llm"
    # Minimum measured segments before the scoreboard ranks an engine (custom models are
    # measured on a held-out set, which is smaller).
    scoreboard_min_segments: int = 200
    custom_model_min_eval_segments: int = 50

    # Own models (LoRA fine-tunes per client, with consent).
    training_min_examples: int = 200
    training_validation_ratio: float = 0.1

    # Quality defaults (spec: QE layer)
    default_threshold: float = 78.0
    band_width: float = 8.0  # senate is convened for threshold - band_width < score < threshold + band_width
    control_sample_rate: float = 0.02
    max_threshold_step_per_week: float = 3.0
    escaped_error_target: float = 0.005
    drift_alarm_ratio: float = 0.30

    # Money
    currency: str = "EUR"
    quote_validity_days: int = 14

    # Webhooks
    webhook_max_attempts: int = 10
    webhook_disable_after_consecutive_failures: int = 500

    # API
    rate_limit_per_minute: int = 6000
    page_size_max: int = 200

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
