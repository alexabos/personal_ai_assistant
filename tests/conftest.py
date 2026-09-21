"""Shared pytest fixtures for isolated database testing.

Uses a dedicated in-memory SQLite engine, wired in via a get_db dependency
override. The app's lifespan (which touches the real assistant.db file) is
never triggered here: the TestClient fixture is not used as a context
manager, so startup/shutdown events do not run.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from assistant.db import models  # noqa: F401  (register tables on Base.metadata)
from assistant.db.database import Base, get_db
from assistant.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _reset_database() -> Generator[None, None, None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """A raw Session for tests that call service functions directly (no HTTP)."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
