from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sahyog_common.files import find_repo_root, load_yaml
from sahyog_common.i18n import SUPPORTED_LOCALES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Sahyog Care Companion"
    app_env: str = "dev"
    app_profile: str = "minimal"
    app_base_url: str = "http://localhost:5705"
    api_base_url: str = "http://localhost:5706"
    cors_origins: str = "http://localhost:5705,http://localhost:5729"
    log_level: str = "INFO"
    app_secret_key: str = ""
    ha_mode: bool = False
    checkpointer_required: bool = False
    supported_locales: str = ",".join(SUPPORTED_LOCALES)
    default_locale: str = "en-IN"
    language_detection_enabled: bool = True

    database_url: str = ""
    database_pool_size: int = 10
    database_pool_overflow: int = 5
    redis_url: str = "redis://redis:6379/0"
    # Worker and scheduler poll separate ARQ queues; a shared queue lets either
    # process claim jobs whose function it does not register.
    arq_worker_queue: str = "sahyog:worker"
    arq_scheduler_queue: str = "sahyog:scheduler"

    keycloak_url: str = "http://keycloak:8080"
    keycloak_public_url: str = "http://localhost:5707"
    keycloak_realm: str = "sahyog"
    keycloak_client_id: str = "sahyog-api"
    keycloak_audience: str = "sahyog-api"
    keycloak_jwks_timeout_seconds: float = 5.0

    litellm_base_url: str = "http://litellm:4000"
    litellm_master_key: str = ""
    litellm_database_url: str = ""
    # Used when LiteLLM is unreachable for local (ollama) aliases.
    ollama_base_url: str = "http://127.0.0.1:11434"
    model_routes_config: str = "config/models.yaml"
    embedding_dim: int = 1024

    mcp_broker_url: str = "http://mcp-broker:8100"
    # Host-side API processes cannot resolve the compose DNS name.
    mcp_broker_public_url: str = "http://127.0.0.1:5709"
    mcp_context_secret: str = ""
    mcp_context_ttl_seconds: int = 120
    pii_service_url: str = "http://mcp-pii:8106"
    pii_gate_timeout_seconds: float = 4.0
    mcp_stt_url: str = "http://mcp-stt:8107"

    clamav_host: str = ""
    clamav_port: int = 3310
    malware_scan_mode: str = "advisory"
    malware_scan_timeout_seconds: float = 20.0

    langfuse_host: str = ""
    langfuse_public_url: str = "http://localhost:5721"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_capture_content: bool = False
    # Attach PII-redacted generation input/output to Langfuse (raw PHI still forbidden).
    langfuse_redacted_io: bool = False
    trace_export_sample_ratio: float = 0.1
    grafana_public_url: str = "http://localhost:5723"
    prometheus_public_url: str = "http://localhost:5722"
    mailpit_public_url: str = "http://localhost:5718"
    # Embed Grafana kiosk view in /ops when the browser can reach GRAFANA_PUBLIC_URL.
    observability_embed_grafana: bool = True

    s3_endpoint_url: str = ""
    s3_public_endpoint_url: str = ""
    s3_region: str = "ap-south-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_documents: str = "sahyog-documents"
    s3_bucket_audio: str = "sahyog-audio"
    s3_bucket_eval: str = "sahyog-eval"
    s3_bucket_anchors: str = "sahyog-audit-anchors"
    s3_bucket_backups: str = "sahyog-backups"
    s3_use_path_style: bool = True
    s3_server_side_encryption: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_auth_mode: str = "password"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_starttls: bool = True
    email_from: str = ""
    email_reply_to: str = ""
    # Prefer SLACK_STAFF_BOT_TOKEN / SLACK_PATIENT_BOT_TOKEN. SLACK_BOT_TOKEN is a
    # legacy alias for the staff token only.
    slack_bot_token: str = ""
    slack_staff_bot_token: str = ""
    slack_patient_bot_token: str = ""
    slack_staff_workspace_id: str = ""
    slack_patient_workspace_id: str = ""
    slack_allowed_channels: str = ""
    slack_patient_allowed_channels: str = ""
    sms_adapter: str = "http"  # http | twilio
    sms_base_url: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = ""
    sms_account_sid: str = ""
    sms_auth_token: str = ""
    sms_from_number: str = ""
    sms_test_to: str = ""
    fhir_base_url: str = ""
    fhir_client_id: str = ""
    fhir_client_secret: str = ""
    fhir_token_url: str = ""
    fhir_timeout_seconds: float = 15.0
    abdm_sandbox_url: str = ""
    abdm_client_id: str = ""
    abdm_client_secret: str = ""
    abdm_timeout_seconds: float = 15.0
    stock_api_key: str = ""
    # Shared key for MCP → API internal tools (scheduling/records/stock). Falls back to stock key.
    internal_api_key: str = ""
    # Host path for scheduled ``scripts/backup.sh`` (ARQ ops.backup). Empty → job fails visibly.
    backup_out_dir: str = ""
    notify_send_external: bool = False
    notify_ops_subject: str = ""
    external_egress_enabled: bool = False

    # Self-hosted Mem0 (docker/mem0) — leave empty to use Postgres preference table only.
    mem0_url: str = ""
    mem0_api_key: str = ""
    mem0_timeout_seconds: float = 15.0
    # Durable non-clinical agent memory: mem0 | pgvector (clinical RAG always app pgvector).
    memory_backend: str = "mem0"

    # OpenDecider / llama.cpp server (optional)
    decider_llama_url: str = ""
    decider_model_path: str = ""

    # Model weight roots (host or container mounts from scripts/download_models.sh)
    whisper_model_dir: str = ""
    gliner_model: str = ""

    # STT: local (mcp-stt/faster-whisper) or cloud (OpenAI-compatible /audio/transcriptions).
    stt_adapter: str = "local"  # local | cloud
    allow_cloud_stt: bool = False
    stt_cloud_base_url: str = ""
    stt_cloud_api_key: str = ""
    stt_cloud_model: str = "whisper-1"
    stt_cloud_timeout_seconds: float = 60.0

    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "sahyog-api"
    otel_traces_sampler_arg: float = 0.1

    config_dir: Path = Field(default_factory=lambda: find_repo_root() / "config")
    version: str = "0.1.0"

    @field_validator("app_env")
    @classmethod
    def _env(cls, value: str) -> str:
        if value not in {"dev", "staging", "production", "test"}:
            raise ValueError("APP_ENV must be dev, staging, production or test")
        return value

    @field_validator("malware_scan_mode")
    @classmethod
    def _scan_mode(cls, value: str) -> str:
        if value not in {"required", "advisory", "disabled"}:
            raise ValueError("MALWARE_SCAN_MODE must be required, advisory or disabled")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def locale_list(self) -> list[str]:
        return [item.strip() for item in self.supported_locales.split(",") if item.strip()]

    @property
    def keycloak_issuer(self) -> str:
        base = self.keycloak_public_url.rstrip("/")
        return f"{base}/realms/{self.keycloak_realm}"

    @property
    def keycloak_jwks_url(self) -> str:
        base = self.keycloak_url.rstrip("/")
        return f"{base}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def smtp_configured(self) -> bool:
        if not self.smtp_host:
            return False
        if self.smtp_auth_mode == "none":
            return True
        return bool(self.smtp_password)

    @property
    def sms_from(self) -> str:
        return (self.sms_from_number or self.sms_sender_id).strip()

    @property
    def sms_configured(self) -> bool:
        adapter = (self.sms_adapter or "http").strip().lower()
        if adapter == "twilio":
            return bool(self.sms_account_sid and self.sms_auth_token and self.sms_from)
        return bool(self.sms_base_url and self.sms_api_key and self.sms_from)

    @property
    def resolved_slack_staff_bot_token(self) -> str:
        return (self.slack_staff_bot_token or self.slack_bot_token).strip()

    @property
    def resolved_slack_patient_bot_token(self) -> str:
        return self.slack_patient_bot_token.strip()

    @property
    def slack_staff_configured(self) -> bool:
        return bool(
            self.resolved_slack_staff_bot_token
            and self.slack_staff_workspace_id
            and self.slack_allowed_channels
        )

    @property
    def slack_patient_configured(self) -> bool:
        return bool(self.resolved_slack_patient_bot_token and self.slack_patient_workspace_id)

    @property
    def resolved_internal_api_key(self) -> str:
        return (self.internal_api_key or self.stock_api_key).strip()

    @property
    def fhir_configured(self) -> bool:
        # Base URL alone is enough for open test servers. Client-credentials auth
        # is used when client_id, client_secret and token_url are all present.
        if not self.fhir_base_url.strip():
            return False
        has_any_auth = bool(self.fhir_client_id or self.fhir_client_secret or self.fhir_token_url)
        if not has_any_auth:
            return True
        return bool(self.fhir_client_id and self.fhir_client_secret and self.fhir_token_url)

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_endpoint_url and self.s3_access_key and self.s3_secret_key)

    def app_config(self) -> dict[str, Any]:
        return load_yaml(self.config_dir / "app.yaml")

    def models_config(self) -> dict[str, Any]:
        configured = Path(self.model_routes_config)
        if configured.is_absolute() or configured.exists():
            return load_yaml(configured)
        return load_yaml(self.config_dir / "models.yaml")

    def validate_startup(self) -> None:
        if self.app_env == "test":
            return
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if self.database_url.startswith("sqlite"):
            raise ValueError("SQLite is not supported; use Postgres 16+ with pgvector")
        if not self.app_secret_key or len(self.app_secret_key) < 32:
            raise ValueError("APP_SECRET_KEY must be at least 32 characters")
        if not self.mcp_context_secret or len(self.mcp_context_secret) < 32:
            raise ValueError("MCP_CONTEXT_SECRET must be at least 32 characters")
        if not self.litellm_master_key:
            raise ValueError("LITELLM_MASTER_KEY is required")
        if self.app_profile not in {"minimal", "core", "full"}:
            raise ValueError("APP_PROFILE must be minimal, core or full")
        if not set(self.locale_list) <= set(SUPPORTED_LOCALES):
            raise ValueError("SUPPORTED_LOCALES contains an unsupported locale")
        if self.malware_scan_mode == "required" and not self.clamav_host:
            raise ValueError("MALWARE_SCAN_MODE=required needs CLAMAV_HOST")
        if self.app_env == "production" and self.malware_scan_mode != "required":
            raise ValueError("production requires MALWARE_SCAN_MODE=required")
        if self.external_egress_enabled and not self.pii_service_url:
            raise ValueError("EXTERNAL_EGRESS_ENABLED needs PII_SERVICE_URL")
        if self.langfuse_capture_content:
            raise ValueError("LANGFUSE_CAPTURE_CONTENT must stay false for PHI safety")
        backend = (self.memory_backend or "mem0").strip().lower()
        if backend not in {"mem0", "pgvector"}:
            raise ValueError("MEMORY_BACKEND must be mem0 or pgvector")
        self.memory_backend = backend
        adapter = (self.stt_adapter or "local").strip().lower()
        if adapter not in {"local", "cloud"}:
            raise ValueError("STT_ADAPTER must be local or cloud")
        if adapter == "cloud":
            if not self.allow_cloud_stt:
                raise ValueError("STT_ADAPTER=cloud requires ALLOW_CLOUD_STT=true")
            if not self.stt_cloud_base_url.strip() or not self.stt_cloud_api_key.strip():
                raise ValueError("cloud STT needs STT_CLOUD_BASE_URL and STT_CLOUD_API_KEY")
            if not self.pii_service_url:
                raise ValueError("cloud STT requires PII_SERVICE_URL (egress gate)")
            if not self.external_egress_enabled:
                raise ValueError("cloud STT requires EXTERNAL_EGRESS_ENABLED=true")


@lru_cache
def get_settings() -> Settings:
    from app.core.vault import apply_secrets

    apply_secrets()
    return Settings()


class FinOpsError(ValueError):
    pass


def load_finops_model(config_dir: Path) -> dict[str, Any]:
    model = load_yaml(config_dir / "finops_model.yaml")
    if model.get("accounting_currency") != "USD":
        raise FinOpsError("FinOps accounting currency must be USD")
    if model.get("display_currency") != "INR":
        raise FinOpsError("FinOps display currency must be INR")
    if not isinstance(model.get("profiles"), dict) or not model["profiles"]:
        raise FinOpsError("FinOps profiles are missing")
    return model


def parse_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None
