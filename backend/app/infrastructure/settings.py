from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOXRIVA_")

    version: str = "0.1.1"
    database_url: str | None = Field(default=None, repr=False)
    database_url_file: Path | None = None
    metrics_token_file: Path | None = None
    redis_url: str | None = None
    dependency_timeout: PositiveFloat = 2
    static_dir: Path = Path("frontend/dist")
    container_monitoring_enabled: bool = True
    snapshot_path: Path | None = None
    snapshot_max_age: PositiveFloat = 12

    secure_session_cookie: bool = True
    session_hours: PositiveInt = 8
    mfa_policy: Literal["optional", "required"] = "optional"

    provider_encryption_keys: SecretStr | None = None
    provider_encryption_key_file: Path | None = None
    smtp_allowed_hosts: list[str] = []

    delivery_max_attempts: int = Field(default=3, ge=1, le=10)
    delivery_retry_base_seconds: PositiveFloat = 5
    delivery_retry_max_seconds: PositiveFloat = 60
    delivery_lease_seconds: int = Field(default=180, ge=10, le=600)
    delivery_payload_ttl_seconds: int = Field(default=86400, ge=1, le=604800)
    delivery_outbox_resend_seconds: int = Field(default=30, ge=5, le=600)
    delivery_provider_concurrency: int = Field(default=2, ge=1, le=20)
    worker_stale_seconds: int = Field(default=30, ge=5, le=300)
    metrics_token: SecretStr | None = None

    @model_validator(mode="after")
    def load_secret_files(self) -> "Settings":
        # Compose secrets keep credentials out of container environment/config output.
        if self.database_url_file is not None:
            self.database_url = self.database_url_file.read_text().strip()
        if self.metrics_token_file is not None:
            self.metrics_token = SecretStr(self.metrics_token_file.read_text().strip())
        return self
