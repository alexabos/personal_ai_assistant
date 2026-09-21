"""Pydantic schemas for the planning API."""

from datetime import date

from pydantic import BaseModel

from assistant.schemas.tasks import TaskRead
from assistant.schemas.weekly_goals import WeeklyGoalRead
from assistant.services.planning_service import DailyPlan


class DailyPlanRead(BaseModel):
    """Aggregated planning snapshot returned by the API."""

    reference_date: date
    relevant_tasks: list[TaskRead]
    overdue_tasks: list[TaskRead]
    goals_falling_behind: list[WeeklyGoalRead]
    suggested_task: TaskRead | None


def daily_plan_to_read(plan: DailyPlan) -> DailyPlanRead:
    """Convert a DailyPlan (ORM objects) into its API/JSON representation.

    Shared by the /plan route and the get_daily_plan tool so the conversion
    is written once, not duplicated per caller.
    """
    return DailyPlanRead(
        reference_date=plan.reference_date,
        relevant_tasks=[TaskRead.model_validate(task) for task in plan.relevant_tasks],
        overdue_tasks=[TaskRead.model_validate(task) for task in plan.overdue_tasks],
        goals_falling_behind=[
            WeeklyGoalRead.model_validate(goal) for goal in plan.goals_falling_behind
        ],
        suggested_task=(
            TaskRead.model_validate(plan.suggested_task) if plan.suggested_task else None
        ),
    )
