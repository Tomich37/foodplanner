import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


class Settings:
    """Application configuration."""

    def __init__(self) -> None:
        def _int_env(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _list_env(name: str) -> tuple[str, ...]:
            raw = os.getenv(name, "")
            values = [item.strip() for item in raw.split(",")]
            return tuple(item for item in values if item)

        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/foodplanner",
        )
        self.secret_key = os.getenv("SECRET_KEY", "foodplanner-secret-key")
        self.static_version = os.getenv("STATIC_VERSION", "24022026-2")
        self.session_max_age = _int_env("SESSION_MAX_AGE", 60 * 60 * 24 * 7)
        self.upload_max_bytes = _int_env("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
        self.max_multipart_body_bytes = _int_env(
            "MAX_MULTIPART_BODY_BYTES", 12 * 1024 * 1024
        )
        self.login_attempt_window_seconds = _int_env(
            "LOGIN_ATTEMPT_WINDOW_SECONDS", 15 * 60
        )
        self.login_max_attempts = _int_env("LOGIN_MAX_ATTEMPTS", 5)
        self.login_block_seconds = _int_env("LOGIN_BLOCK_SECONDS", 10 * 60)
        self.csrf_trusted_origins = _list_env("CSRF_TRUSTED_ORIGINS")


settings = Settings()
