from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables prefixed with RQ_ (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="RQ_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/routinequest"

    # URL of the parent PWA, used in magic-link emails and CORS
    public_app_url: str = "http://localhost:5173"

    session_ttl_days: int = 30
    magic_link_ttl_min: int = 15
    claim_code_ttl_min: int = 15
    cookie_secure: bool = True

    # Web Push (VAPID). Generate with: python -m app.cli vapid-keys
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@routinequest.invalid"

    # Email delivery for magic links: "console" logs the link (dev only), "smtp" sends it.
    mailer: Literal["console", "smtp"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Routine Quest <no-reply@routinequest.invalid>"

    # Latest firmware offered to devices (empty = no OTA)
    fw_latest_version: str = ""
    fw_latest_url: str = ""

    # Push notifications for events older than this are skipped (offline backlog)
    notify_max_age_min: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
