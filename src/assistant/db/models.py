"""ORM models.

Application models (Task, WeeklyGoal) live here. Their status/priority enums
are the single source of truth shared with the Pydantic schemas, so the API
and the database layer can never drift apart.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from assistant.db.database import Base

__all__ = [
    "Base",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "WeeklyGoal",
    "WeeklyGoalStatus",
]


class TaskStatus(StrEnum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Priority level of a task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WeeklyGoalStatus(StrEnum):
    """Lifecycle status of a weekly goal."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _utcnow() -> datetime:
    """Return a naive UTC timestamp, consistent with SQLite storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def _string_enum(enum_cls: type[StrEnum]) -> Any:
    """Store enum members by their string value rather than their name."""
    return SAEnum(
        enum_cls,
        values_callable=lambda cls: [member.value for member in cls],
        native_enum=False,
    )


class Task(Base):
    """A single actionable task."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[TaskStatus] = mapped_column(
        _string_enum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    priority: Mapped[TaskPriority] = mapped_column(
        _string_enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False
    )
    due_date: Mapped[date | None] = mapped_column(default=None)
    estimated_minutes: Mapped[int | None] = mapped_column(default=None)
    category: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)


class WeeklyGoal(Base):
    """A weekly, time-boxed goal."""

    __tablename__ = "weekly_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(default=None)
    week_start: Mapped[date] = mapped_column(nullable=False)
    target_minutes: Mapped[int | None] = mapped_column(default=None)
    completed_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[WeeklyGoalStatus] = mapped_column(
        _string_enum(WeeklyGoalStatus), default=WeeklyGoalStatus.ACTIVE, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, nullable=False)
