from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class ConfigurationError(ValueError):
    """Raised when a required runtime configuration value is invalid."""


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value.")


def _origins(value: str) -> tuple[str, ...]:
    origins = tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())
    if not origins or "*" in origins:
        raise ConfigurationError("FRONTEND_URL must contain one or more explicit origins, never '*'.")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.params or parsed.query or parsed.fragment:
            raise ConfigurationError("FRONTEND_URL origins must be complete http or https origins without paths.")
    return origins


@dataclass(frozen=True)
class Settings:
    app_env: str
    cors_origins: tuple[str, ...]
    dry_run: bool
    mongodb_uri: str | None = None
    cloud_ai: bool = False
    local_ai: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    def __post_init__(self) -> None:
        if self.app_env not in {"development", "test", "production"}:
            raise ConfigurationError("APP_ENV must be development, test, or production.")
        if not self.app_host.strip():
            raise ConfigurationError("APP_HOST must not be empty.")
        if not 1 <= self.app_port <= 65535:
            raise ConfigurationError("APP_PORT must be between 1 and 65535.")
        _origins(",".join(self.cors_origins))

    @classmethod
    def from_environment(cls) -> "Settings":
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        if app_env not in {"development", "test", "production"}:
            raise ConfigurationError("APP_ENV must be development, test, or production.")

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173,http://localhost:5174")
        mongodb_uri = os.getenv("MONGODB_URI", "").strip() or None
        try:
            app_port = int(os.getenv("APP_PORT", "8000"))
        except ValueError as cause:
            raise ConfigurationError("APP_PORT must be an integer.") from cause
        return cls(
            app_env=app_env,
            cors_origins=_origins(frontend_url),
            dry_run=_read_bool("KYRA_DRY_RUN", default=True),
            app_host=os.getenv("APP_HOST", "0.0.0.0").strip(),
            app_port=app_port,
            mongodb_uri=mongodb_uri,
            cloud_ai=_read_bool("KYRA_CLOUD_AI", default=False),
            local_ai=_read_bool("KYRA_LOCAL_AI", default=False),
        )
