"""LLM-callable tool wrapping the schedule-combining service.

Same thin-translator pattern as calendar_tools.py/notion_tools.py: a small
Pydantic args model validates the LLM's raw arguments, and the handler calls
straight into schedule_service - no Calendar/Notion API logic lives here.
This tool only ever proposes a schedule; it has no path to creating a
calendar event or modifying a Notion task (see schedule_service.py).

The `db` parameter on the handler is required by the shared Tool.handler
signature but unused.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from assistant.services import notion_service, schedule_service
from assistant.tools.registry import Tool

_DATETIME_DESCRIPTION = (
    "ISO-8601 datetime with an explicit UTC offset, e.g. "
    "'2026-09-24T10:00:00+02:00'. Never a naive datetime without an offset."
)
_CONFIGURED_SOURCES = ", ".join(sorted(notion_service.get_configured_sources())) or (
    "(none configured)"
)


class ProposeScheduleArgs(BaseModel):
    """Arguments for the propose_schedule tool."""

    start_datetime: datetime = Field(
        description=f"Start of the window to plan within. {_DATETIME_DESCRIPTION}"
    )
    end_datetime: datetime = Field(
        description=f"End of the window to plan within. {_DATETIME_DESCRIPTION}"
    )
    source: str = Field(
        default="all",
        description=(
            f"Which Notion task source to draw from. One of: {_CONFIGURED_SOURCES}, "
            "or 'all' (default) to consider every configured source."
        ),
    )

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetime must include an explicit UTC offset, e.g. '+02:00'")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ProposeScheduleArgs":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        return self


def propose_schedule(db: Session, args: BaseModel) -> dict[str, Any]:
    """Return a draft schedule (never committed to the calendar) as
    JSON-serializable data."""
    assert isinstance(args, ProposeScheduleArgs)
    schedule = schedule_service.build_schedule(
        args.start_datetime, args.end_datetime, source=args.source
    )
    return schedule.model_dump(mode="json")


PROPOSE_SCHEDULE_TOOL = Tool(
    name="propose_schedule",
    description=(
        "Propose a draft schedule for a time window by combining the user's "
        "real free Calendar time with their ranked Notion tasks (by "
        "deadline, then priority). Call this for planning questions like "
        "'what should I do this afternoon' or 'plan my day'. This ONLY "
        "produces a draft - it never creates, modifies, or commits anything "
        "to the Calendar or Notion. Present the result as a suggestion; if "
        "the user wants it actually added to their calendar, that requires "
        "a separate, explicit follow-up request using create_calendar_event. "
        "Tasks that don't fit in the available free time, or have no known "
        "duration, are returned separately in 'unscheduled' with a reason "
        "('missing_duration' or 'no_free_block_long_enough') - mention them "
        "too rather than omitting them."
    ),
    args_model=ProposeScheduleArgs,
    handler=propose_schedule,
)

SCHEDULE_TOOLS: list[Tool] = [PROPOSE_SCHEDULE_TOOL]
