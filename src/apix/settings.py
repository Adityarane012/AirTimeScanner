"""Central config, read once from .env. See env.example for the full list."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://apix_app:CHANGE_ME@localhost:5432/apix"
    raw_store_path: Path = Path("./data/raw")
    apix_user_agent: str = "APIx-Collector/0.1 (+mailto:unset@example.com)"
    apix_contact_email: str = "unset@example.com"
    app_env: str = "dev"


settings = Settings()
