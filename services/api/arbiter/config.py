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
    # Master key for secrets stored in the database (SSO client secrets, BYOK keys). Comma
    # separated for rotation: the first key encrypts, every key decrypts. A Fernet key
    # (urlsafe base64 of 32 bytes) or any passphrase of 32+ characters (derived with HKDF).
    secrets_key: str = Field(default="dev-only-secrets-key-change-me-not-for-production", min_length=32)
    # Origin of the web app; SSO redirect_uri is <web_base_url>/api/sso/callback and invite
    # links point at <web_base_url>/accept-invite.
    web_base_url: str = "http://localhost:3000"
    invite_ttl_hours: int = 24 * 7
    sso_state_ttl_seconds: int = 600
    # DNS-over-HTTPS resolver (JSON API) used to check SSO domain TXT records.
    doh_url: str = "https://cloudflare-dns.com/dns-query"
    # Audit log: take the client IP from X-Forwarded-For (only behind a trusted reverse proxy).
    trust_proxy_headers: bool = False
    audit_export_max_rows: int = 50_000

    # Providers. Empty string = not configured.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    deepl_api_key: str = ""
    google_api_key: str = ""
    embedding_provider: Literal["mock", "openai"] = "mock"

    # Engines used when no scoreboard data exists for a pair (R-MT-02).
    default_mt_engine: str = "mock-mt"
    default_judge_engine: str = "mock-llm"

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
