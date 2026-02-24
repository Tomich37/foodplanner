import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


class Settings:
    """Application configuration."""

    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/foodplanner",
        )
        self.secret_key = os.getenv("SECRET_KEY", "foodplanner-secret-key")
        self.static_version = os.getenv("STATIC_VERSION", "24022026")


settings = Settings()
