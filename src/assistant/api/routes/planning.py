"""HTTP routes for the deterministic planning engine."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from assistant.db.database import get_db
from assistant.schemas.planning import DailyPlanRead, daily_plan_to_read
from assistant.services import planning_service

router = APIRouter(prefix="/plan", tags=["planning"])


@router.get("", response_model=DailyPlanRead)
def get_daily_plan(
    db: Session = Depends(get_db),
    available_minutes: int | None = None,
) -> DailyPlanRead:
    """Return today's planning snapshot: relevant/overdue tasks, goals falling
    behind, and a suggested next task given an optional time budget."""
    plan = planning_service.build_daily_plan(db, available_minutes=available_minutes)
    return daily_plan_to_read(plan)
