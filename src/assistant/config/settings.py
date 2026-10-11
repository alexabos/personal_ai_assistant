"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the assistant application."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Personal AI Assistant"
    environment: str = "development"
    database_url: str = "sqlite:///./assistant.db"
    log_level: str = "INFO"

    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tool_iterations: int = 4

    google_calendar_credentials_file: str = "credentials/google_calendar_credentials.json"
    google_calendar_token_file: str = "credentials/google_calendar_token.json"
    google_calendar_id: str = "primary"
    default_timezone: str = "Europe/Madrid"

    notion_api_key: str | None = None
    notion_database_university: str | None = None
    notion_database_sanofi: str | None = None
    notion_database_personal: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
