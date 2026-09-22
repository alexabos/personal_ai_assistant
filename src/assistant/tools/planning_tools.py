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
        description=(
            "The user's stated time budget in minutes, passed exactly as they said "
            "it - including invalid values such as zero or negative numbers. Do not "
            "silently correct, clamp, or round it, and do not omit it just because "
            "it looks invalid; this tool validates it and will report back if it "
            "isn't usable. Omit this field only when the user did not state any "
            "time constraint at all."
        ),
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
        "suggestion - optionally pass available_minutes if they state how much "
        "time they have. Pass their stated number exactly, even if it looks "
        "invalid (e.g. negative or zero) - never silently correct or drop it "
        "yourself. Only omit available_minutes when no time constraint was "
        "mentioned at all."
    ),
    args_model=GetDailyPlanArgs,
    handler=get_daily_plan,
)

PLANNING_TOOLS: list[Tool] = [GET_DAILY_PLAN_TOOL]
