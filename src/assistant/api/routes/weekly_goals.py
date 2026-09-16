"""HTTP routes for weekly goal management."""

from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from assistant.db.database import get_db
from assistant.db.models import WeeklyGoalStatus
from assistant.schemas.weekly_goals import WeeklyGoalCreate, WeeklyGoalRead, WeeklyGoalUpdate
from assistant.services import weekly_goal_service

router = APIRouter(prefix="/weekly-goals", tags=["weekly-goals"])


@router.post("", response_model=WeeklyGoalRead, status_code=status.HTTP_201_CREATED)
def create_weekly_goal(
    payload: WeeklyGoalCreate, db: Session = Depends(get_db)
) -> WeeklyGoalRead:
    """Create a new weekly goal. week_start is normalized to Monday."""
    goal = weekly_goal_service.create_weekly_goal(
        db,
        title=payload.title,
        description=payload.description,
        week_start=payload.week_start,
        target_minutes=payload.target_minutes,
    )
    return WeeklyGoalRead.model_validate(goal)


@router.get("", response_model=list[WeeklyGoalRead])
def list_weekly_goals(
    db: Session = Depends(get_db),
    week_start: date | None = None,
    status: WeeklyGoalStatus | None = None,
) -> list[WeeklyGoalRead]:
    """List weekly goals, optionally filtered by week_start and status."""
    goals = weekly_goal_service.list_weekly_goals(db, week_start=week_start, status=status)
    return [WeeklyGoalRead.model_validate(goal) for goal in goals]


@router.get("/{goal_id}", response_model=WeeklyGoalRead)
def get_weekly_goal(goal_id: int, db: Session = Depends(get_db)) -> WeeklyGoalRead:
    """Retrieve a single weekly goal by id."""
    goal = weekly_goal_service.get_weekly_goal(db, goal_id)
    return WeeklyGoalRead.model_validate(goal)


@router.patch("/{goal_id}", response_model=WeeklyGoalRead)
def update_weekly_goal(
    goal_id: int, payload: WeeklyGoalUpdate, db: Session = Depends(get_db)
) -> WeeklyGoalRead:
    """Partially update a weekly goal."""
    goal = weekly_goal_service.update_weekly_goal(
        db,
        goal_id,
        title=payload.title,
        description=payload.description,
        week_start=payload.week_start,
        target_minutes=payload.target_minutes,
        completed_minutes=payload.completed_minutes,
        status=payload.status,
    )
    return WeeklyGoalRead.model_validate(goal)


@router.post("/{goal_id}/complete", response_model=WeeklyGoalRead)
def complete_weekly_goal(goal_id: int, db: Session = Depends(get_db)) -> WeeklyGoalRead:
    """Mark a weekly goal as completed."""
    goal = weekly_goal_service.complete_weekly_goal(db, goal_id)
    return WeeklyGoalRead.model_validate(goal)


@router.post("/{goal_id}/cancel", response_model=WeeklyGoalRead)
def cancel_weekly_goal(goal_id: int, db: Session = Depends(get_db)) -> WeeklyGoalRead:
    """Mark a weekly goal as cancelled."""
    goal = weekly_goal_service.cancel_weekly_goal(db, goal_id)
    return WeeklyGoalRead.model_validate(goal)
