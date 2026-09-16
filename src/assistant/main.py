"""FastAPI application entry point."""

from fastapi import FastAPI

from assistant.api.routes import health
from assistant.config.settings import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(health.router)
