"""Settings from the environment (.env locally, Secret Manager on Cloud Run).

Loaded once and validated at startup: a missing required value stops the app with a clear error.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    app_origin: str  # comma-separated if the app is reachable on several domains
    # Members: these emails use the app's OpenRouter key (with a monthly cap). Comma-separated.
    allowed_emails: str = ""
    # OPEN_SIGNUP=true: any verified Google account can sign in as a guest. Guests must add
    # their own OpenRouter key before the AI runs, so they never spend the app's key.
    open_signup: bool = False

    # Neon: pooled URL for the app, direct (unpooled) URL for migrations.
    database_url: str
    database_url_unpooled: str | None = None

    app_encryption_key: str
    openrouter_api_key: str

    # Optional: without keys, tracing is off and the app still works.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "dev"

    # Google sign-in (Firebase web config; public values).
    firebase_project_id: str = ""
    firebase_web_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_app_id: str = ""

    # Web push (VAPID). Optional: without them reminders still show in the app.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    cron_secret: str = ""
    # Who sees the hosting consoles and the app's own AI credit in Settings (comma-separated).
    admin_emails: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.app_origin.split(",") if o.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
