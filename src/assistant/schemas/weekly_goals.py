"""Pydantic schemas for the weekly goal API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from assistant.db.models import WeeklyGoalStatus


class WeeklyGoalCreate(BaseModel):
    """Payload to create a new weekly goal."""

    title: str = Field(min_length=1)
    description: str | None = None
    week_start: date
    target_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped


class WeeklyGoalUpdate(BaseModel):
    """Payload to partially update an existing weekly goal."""

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    week_start: date | None = None
    target_minutes: int | None = Field(default=None, gt=0)
    completed_minutes: int | None = Field(default=None, ge=0)
    status: WeeklyGoalStatus | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped


class WeeklyGoalRead(BaseModel):
    """Weekly goal representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    week_start: date
    target_minutes: int | None
    completed_minutes: int
    status: WeeklyGoalStatus
    created_at: datetime
