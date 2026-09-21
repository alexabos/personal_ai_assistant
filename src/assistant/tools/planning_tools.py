"""LLM-callable tools wrapping the planning service.

Each tool here is a thin translator: it declares a small Pydantic args model
(the LLM's-eye view of the tool, and validation for the LLM's raw arguments),
and its handler calls straight into planning_service - the same function the
GET /plan route calls. No planning rule is duplicated here.
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from assistant.schemas.planning import daily_plan_to_read
from assistant.services import planning_service
from assistant.tools.registry import Tool


class GetDailyPlanArgs(BaseModel):
    """Arguments for the get_daily_plan tool."""

    available_minutes: int | None = Field(
        default=None,
        gt=0,
        description="How many minutes the user has available right now, if known.",
    )


def get_daily_plan(db: Session, args: BaseModel) -> dict[str, Any]:
    """Return the user's current planning snapshot as a JSON-serializable dict."""
    assert isinstance(args, GetDailyPlanArgs)
    plan = planning_service.build_daily_plan(db, available_minutes=args.available_minutes)
    return daily_plan_to_read(plan).model_dump(mode="json")


GET_DAILY_PLAN_TOOL = Tool(
    name="get_daily_plan",
    description=(
        "Get the user's current planning snapshot: tasks relevant today, overdue "
        "tasks, weekly goals falling behind pace, and a suggested next task. Call "
        "this whenever the user asks what to do, what's overdue, or wants a task "
        "suggestion - optionally pass available_minutes if they mention how much "
        "time they have."
    ),
    args_model=GetDailyPlanArgs,
    handler=get_daily_plan,
)

PLANNING_TOOLS: list[Tool] = [GET_DAILY_PLAN_TOOL]
