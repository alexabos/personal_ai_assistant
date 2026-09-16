"""Business logic for weekly goal management.

Framework-agnostic by design: see task_service.py for the rationale.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.db.models import WeeklyGoal, WeeklyGoalStatus
from assistant.services.errors import InvalidStateTransitionError, NotFoundError


def normalize_week_start(value: date) -> date:
    """Normalize a date to the Monday of its calendar week."""
    return value - timedelta(days=value.weekday())


def create_weekly_goal(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    week_start: date,
    target_minutes: int | None = None,
) -> WeeklyGoal:
    """Create and persist a new weekly goal, normalizing week_start to Monday."""
    goal = WeeklyGoal(
        title=title,
        description=description,
        week_start=normalize_week_start(week_start),
        target_minutes=target_minutes,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def get_weekly_goal(db: Session, goal_id: int) -> WeeklyGoal:
    """Return a weekly goal by id, or raise NotFoundError."""
    goal = db.get(WeeklyGoal, goal_id)
    if goal is None:
        raise NotFoundError(f"Weekly goal {goal_id} not found")
    return goal


def list_weekly_goals(
    db: Session,
    *,
    week_start: date | None = None,
    status: WeeklyGoalStatus | None = None,
) -> list[WeeklyGoal]:
    """List weekly goals, optionally filtered by (normalized) week_start and status."""
    stmt = select(WeeklyGoal)
    if week_start is not None:
        stmt = stmt.where(WeeklyGoal.week_start == normalize_week_start(week_start))
    if status is not None:
        stmt = stmt.where(WeeklyGoal.status == status)
    stmt = stmt.order_by(WeeklyGoal.week_start.desc())
    return list(db.execute(stmt).scalars().all())


def update_weekly_goal(
    db: Session,
    goal_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    week_start: date | None = None,
    target_minutes: int | None = None,
    completed_minutes: int | None = None,
    status: WeeklyGoalStatus | None = None,
) -> WeeklyGoal:
    """Partially update a weekly goal's fields."""
    goal = get_weekly_goal(db, goal_id)

    if title is not None:
        goal.title = title
    if description is not None:
        goal.description = description
    if week_start is not None:
        goal.week_start = normalize_week_start(week_start)
    if target_minutes is not None:
        goal.target_minutes = target_minutes
    if completed_minutes is not None:
        goal.completed_minutes = completed_minutes
    if status is not None:
        goal.status = status

    db.commit()
    db.refresh(goal)
    return goal


def complete_weekly_goal(db: Session, goal_id: int) -> WeeklyGoal:
    """Mark a weekly goal as completed.

    Idempotent if already completed. Rejects cancelled goals.
    """
    goal = get_weekly_goal(db, goal_id)
    if goal.status == WeeklyGoalStatus.CANCELLED:
        raise InvalidStateTransitionError(
            f"Weekly goal {goal_id} is cancelled and cannot be completed"
        )
    if goal.status != WeeklyGoalStatus.COMPLETED:
        goal.status = WeeklyGoalStatus.COMPLETED
        db.commit()
        db.refresh(goal)
    return goal


def cancel_weekly_goal(db: Session, goal_id: int) -> WeeklyGoal:
    """Mark a weekly goal as cancelled.

    Idempotent if already cancelled. Rejects completed goals.
    """
    goal = get_weekly_goal(db, goal_id)
    if goal.status == WeeklyGoalStatus.COMPLETED:
        raise InvalidStateTransitionError(
            f"Weekly goal {goal_id} is completed and cannot be cancelled"
        )
    if goal.status != WeeklyGoalStatus.CANCELLED:
        goal.status = WeeklyGoalStatus.CANCELLED
        db.commit()
        db.refresh(goal)
    return goal
