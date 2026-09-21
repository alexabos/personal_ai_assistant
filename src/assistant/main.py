"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from assistant.api.routes import health, planning, tasks, weekly_goals
from assistant.config.settings import get_settings
from assistant.db.database import init_db
from assistant.services.errors import InvalidStateTransitionError, NotFoundError

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(weekly_goals.router)
app.include_router(planning.router)


@app.exception_handler(NotFoundError)
async def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    """Translate a missing-entity service error into a 404 response."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(InvalidStateTransitionError)
async def handle_invalid_transition(
    request: Request, exc: InvalidStateTransitionError
) -> JSONResponse:
    """Translate an illegal status transition into a 409 response."""
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})
