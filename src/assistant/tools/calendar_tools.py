"""LLM-callable tools wrapping the Google Calendar service.

Each tool here is a thin translator, same pattern as planning_tools.py: it
declares a small Pydantic args model (validation for the LLM's raw, untrusted
arguments) and a handler that calls straight into calendar_service - no
Google API logic lives here.

The `db` parameter on each handler is required by the shared Tool.handler
signature but unused: calendar tools talk to Google Calendar, not the local
database.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from assistant.services import calendar_service
from assistant.services.calendar_service import EVENT_COLORS
from assistant.tools.registry import Tool

_DATETIME_DESCRIPTION = (
    "ISO-8601 datetime with an explicit UTC offset, e.g. "
    "'2026-09-24T10:00:00+02:00'. Never a naive datetime without an offset."
)
_VALID_COLORS = ", ".join(sorted(EVENT_COLORS))


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include an explicit UTC offset, e.g. '+02:00'")
    return value


class ListCalendarEventsArgs(BaseModel):
    """Arguments for the list_calendar_events tool."""

    start_datetime: datetime = Field(description=f"Start of the range. {_DATETIME_DESCRIPTION}")
    end_datetime: datetime = Field(description=f"End of the range. {_DATETIME_DESCRIPTION}")

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)

    @model_validator(mode="after")
    def validate_range(self) -> "ListCalendarEventsArgs":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        return self


class CreateCalendarEventArgs(BaseModel):
    """Arguments for the create_calendar_event tool."""

    title: str = Field(min_length=1, description="Event title.")
    start_datetime: datetime = Field(description=f"Event start. {_DATETIME_DESCRIPTION}")
    end_datetime: datetime = Field(description=f"Event end. {_DATETIME_DESCRIPTION}")
    description: str | None = Field(default=None, description="Optional event description.")
    location: str | None = Field(default=None, description="Optional event location.")
    calendar_name: str | None = Field(
        default=None,
        description=(
            "Name of a specific calendar (the user's main calendar, or a shared "
            "one) to create the event on, exactly as the user said it - e.g. "
            "'Família Rodes Abos'. Omit to use the user's main calendar."
        ),
    )
    color: str | None = Field(
        default=None,
        description=(
            f"Event color - must be one of these exact names: {_VALID_COLORS}. "
            "Google Calendar has no custom/personal color names - if the user "
            "names something else (e.g. a person's name), ask them to pick one "
            "of the valid names instead of guessing."
        ),
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and value.strip().lower() not in EVENT_COLORS:
            raise ValueError(f"color must be one of: {_VALID_COLORS}")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "CreateCalendarEventArgs":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        return self


def list_calendar_events(db: Session, args: BaseModel) -> dict[str, Any]:
    """Return calendar events in the requested range as JSON-serializable data."""
    assert isinstance(args, ListCalendarEventsArgs)
    events = calendar_service.list_events(args.start_datetime, args.end_datetime)
    return {"events": [event.model_dump(mode="json") for event in events]}


def list_free_time(db: Session, args: BaseModel) -> dict[str, Any]:
    """Return free (unscheduled) time blocks in the requested range."""
    assert isinstance(args, ListCalendarEventsArgs)
    blocks = calendar_service.list_free_blocks(args.start_datetime, args.end_datetime)
    return {"free_blocks": [block.model_dump(mode="json") for block in blocks]}


def create_calendar_event(db: Session, args: BaseModel) -> dict[str, Any]:
    """Create a calendar event and return a confirmation as JSON-serializable data."""
    assert isinstance(args, CreateCalendarEventArgs)
    event = calendar_service.create_event(
        args.title,
        args.start_datetime,
        args.end_datetime,
        description=args.description,
        location=args.location,
        calendar_name=args.calendar_name,
        color=args.color,
    )
    return {"status": "created", "event": event.model_dump(mode="json")}


LIST_CALENDAR_EVENTS_TOOL = Tool(
    name="list_calendar_events",
    description=(
        "List the user's Google Calendar events that start within a given time "
        "range, across all of their calendars (their main calendar and any "
        "shared calendars they have access to). Call this whenever the user "
        "asks what's on their calendar, what they have scheduled, or whether "
        "they're free at a given time. Both start_datetime and end_datetime "
        "must be timezone-aware ISO-8601 datetimes - compute the exact range "
        "from what the user said (e.g. 'tomorrow' or 'this afternoon') using "
        "the user's Europe/Madrid timezone."
    ),
    args_model=ListCalendarEventsArgs,
    handler=list_calendar_events,
)

LIST_FREE_TIME_TOOL = Tool(
    name="list_free_time",
    description=(
        "List the user's free (unscheduled) time blocks within a given time "
        "range, computed from their actual Google Calendar. Call this when "
        "planning or proposing a schedule - e.g. 'what should I do this "
        "afternoon' - to find real gaps before suggesting what to do in "
        "them. Both start_datetime and end_datetime must be timezone-aware "
        "ISO-8601 datetimes using the user's Europe/Madrid timezone."
    ),
    args_model=ListCalendarEventsArgs,
    handler=list_free_time,
)

CREATE_CALENDAR_EVENT_TOOL = Tool(
    name="create_calendar_event",
    description=(
        "Create a new event on the user's Google Calendar. Call this when the "
        "user asks to schedule, add, or book something. Both start_datetime and "
        "end_datetime must be timezone-aware ISO-8601 datetimes in the user's "
        "Europe/Madrid timezone, and end_datetime must be after start_datetime. "
        "If the user names a specific calendar (their main one, or a shared "
        "one), pass it as calendar_name exactly as they said it - this tool "
        "will resolve it or report back if it can't find a unique match. "
        f"If the user asks for a color, it must be one of: {_VALID_COLORS} - if "
        "they name something else, ask them to pick one of these instead of "
        "guessing. Only report the event as created if this tool succeeds - "
        "never assume or claim success otherwise."
    ),
    args_model=CreateCalendarEventArgs,
    handler=create_calendar_event,
)

CALENDAR_TOOLS: list[Tool] = [
    LIST_CALENDAR_EVENTS_TOOL,
    LIST_FREE_TIME_TOOL,
    CREATE_CALENDAR_EVENT_TOOL,
]
