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
    # Where the web app runs: links in vendor offer e-mails (no-login vendor workbench).
    web_base_url: str = "http://localhost:3000"

    # Seller (for invoices). Tax treatment needs legal/tax review before public launch.
    seller_country: str = ""
    vat_rate: str = "0"

    # Auth
    jwt_secret: str = Field(default="dev-only-change-me-not-for-production-use", min_length=32)
    jwt_ttl_minutes: int = 60 * 12
    # Master key for secrets stored in the database (SSO client secrets, engine keys; D-056). Comma
    # separated for rotation: the first key encrypts, every key decrypts. A Fernet key
    # (urlsafe base64 of 32 bytes) or any passphrase of 32+ characters (derived with HKDF).
    secrets_key: str = Field(default="dev-only-secrets-key-change-me-not-for-production", min_length=32)
    # Origin of the web app; SSO redirect_uri is <web_base_url>/api/sso/callback, invite
    # links point at <web_base_url>/accept-invite, and emails link back to it (password reset,
    # job pages).
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

    # EU processing route (D-057). Bedrock: AWS keys for the platform account; model is an
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

    # Blob storage (D-051 storage backends). local = files under storage_dir (dev, test,
    # single box); s3 = any S3-compatible object store (Hetzner Object Storage in production).
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str = ""  # e.g. https://fsn1.your-objectstorage.com; empty = AWS default
    s3_region: str = "eu-central"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_path_style: bool = True  # path-style addressing works on every S3-compatible store
    upload_url_ttl_seconds: int = 3600  # presigned PUT lifetime for direct uploads
    download_url_ttl_seconds: int = 300  # presigned GET lifetime for downloads and evidence

    # Email. log = written to the email_messages table and the log only (dev, test);
    # smtp = any transactional provider through SMTP with TLS.
    mail_backend: Literal["log", "smtp"] = "log"
    mail_from: str = "Arbiter <no-reply@localhost>"
    mail_reply_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout_seconds: float = 20.0
    password_reset_ttl_minutes: int = 60

    # Observability. Everything is off when its setting is empty.
    posthog_key: str = ""  # project API key (write-only, public by design)
    posthog_host: str = "https://eu.i.posthog.com"
    otel_endpoint: str = ""  # OTLP/HTTP base, e.g. https://otel.example.com (no /v1/traces)
    otel_headers: str = ""  # comma separated key=value pairs sent with every OTLP export
    otel_service_name: str = ""  # default arbiter-api / arbiter-worker
    heartbeat_url: str = ""  # worker pings it (GET) every heartbeat_interval_seconds
    heartbeat_interval_seconds: int = 60

    # Build identity, baked into the image by CI (GET /healthz reports them).
    git_sha: str = "unknown"
    version: str = "0.1.0"

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
