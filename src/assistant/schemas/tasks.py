"""Pydantic schemas for the task API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from assistant.db.models import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    """Payload to create a new task."""

    title: str = Field(min_length=1)
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    category: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped


class TaskUpdate(BaseModel):
    """Payload to partially update an existing task."""

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    category: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped


class TaskRead(BaseModel):
    """Task representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    estimated_minutes: int | None
    category: str | None
    created_at: datetime
    completed_at: datetime | None
