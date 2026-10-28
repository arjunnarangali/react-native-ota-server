from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py is at app/core/config.py in this standalone repository.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "RN OTA API"
    database_url: str
    ota_admin_token: str | None = None
    ota_signing_public_key_path: Path = (
        REPOSITORY_ROOT / ".local-keys/ota-publisher-public.pem"
    )
    ota_storage_dir: Path = REPOSITORY_ROOT / "storage/releases"
    ota_max_bundle_size_bytes: int = 100 * 1024 * 1024
    ota_api_base_url: str = "http://127.0.0.1:8000"
    ota_public_base_url: str = ""

    @field_validator("ota_signing_public_key_path", "ota_storage_dir", mode="before")
    @classmethod
    def resolve_repository_paths(cls, value: Path | str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else REPOSITORY_ROOT / path

    @field_validator("ota_public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OTA_PUBLIC_BASE_URL must be an HTTP(S) origin without a path")
        return value

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Load settings once so routes share one consistent configuration."""
    return Settings()


settings = get_settings()
