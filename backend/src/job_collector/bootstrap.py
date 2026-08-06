from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = Field("job-collector", alias="APP_NAME")
    app_env: str = Field("development", alias="APP_ENV")
    app_version: str = Field("0.1.0", alias="APP_VERSION")
    timezone: str = Field("Asia/Seoul", alias="TZ")
    database_url: str = Field("sqlite+aiosqlite:///./job_collector.db", alias="DATABASE_URL")
    admin_api_key: str = Field("dev-admin-key", alias="ADMIN_API_KEY")
    profiles_dir: Path = Path("profiles")
    wanted_enabled: bool = Field(True, alias="WANTED_ENABLED")
    wanted_base_url: str = Field("https://www.wanted.co.kr", alias="WANTED_BASE_URL")
    wanted_request_delay_seconds: float = Field(1.5, alias="WANTED_REQUEST_DELAY_SECONDS")
    wanted_max_concurrency: int = Field(2, alias="WANTED_MAX_CONCURRENCY")
    saramin_enabled: bool = Field(False, alias="SARAMIN_ENABLED")
    saramin_access_key: str | None = Field(None, alias="SARAMIN_ACCESS_KEY")
    saramin_base_url: str = Field("https://oapi.saramin.co.kr", alias="SARAMIN_BASE_URL")
    saramin_public_enabled: bool = Field(False, alias="SARAMIN_PUBLIC_ENABLED")
    saramin_public_base_url: str = Field("https://www.saramin.co.kr", alias="SARAMIN_PUBLIC_BASE_URL")
    saramin_public_request_delay_seconds: float = Field(1.5, alias="SARAMIN_PUBLIC_REQUEST_DELAY_SECONDS")
    jobkorea_enabled: bool = Field(False, alias="JOBKOREA_ENABLED")
    jobkorea_base_url: str = Field("https://www.jobkorea.co.kr", alias="JOBKOREA_BASE_URL")
    jobkorea_request_delay_seconds: float = Field(1.5, alias="JOBKOREA_REQUEST_DELAY_SECONDS")
    samsung_enabled: bool = Field(False, alias="SAMSUNG_ENABLED")
    lg_enabled: bool = Field(False, alias="LG_ENABLED")
    hyundai_enabled: bool = Field(False, alias="HYUNDAI_ENABLED")
    http_timeout_seconds: float = Field(20, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(3, alias="HTTP_MAX_RETRIES")
    scheduler_enabled: bool = Field(False, alias="SCHEDULER_ENABLED")
    sync_cron: str = Field("0 2 * * *", alias="SYNC_CRON")
    recheck_cron: str = Field("0 3 * * *", alias="RECHECK_CRON")
    default_profile: str = Field("mobility_sdv_security_cpp", alias="DEFAULT_PROFILE")
    cors_origins: str = Field("http://localhost:5173", alias="CORS_ORIGINS")
