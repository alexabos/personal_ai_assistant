"""Google Calendar integration: authentication, listing, and creating events.

Framework-agnostic by design: see task_service.py for the rationale. This
module never starts an interactive OAuth flow - that is the explicit job of
scripts/google_calendar_auth.py. If no valid, non-interactively-refreshable
credential exists, functions here raise CalendarServiceError rather than
opening a browser, so normal assistant execution never blocks on user input.

Listing spans every calendar visible to the account (main + shared);
creating an event still targets one specific calendar (google_calendar_id,
default "primary") since a new event has to go somewhere specific.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel

from assistant.config.settings import get_settings
from assistant.services.errors import CalendarServiceError

# Read/write events, plus read-only enumeration of the account's calendars
# (needed to list events across shared calendars, not just the primary one).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]

# Google Calendar's fixed event-color palette (colorId 1-11). There is no way
# to register a custom/personal color name - an unrecognized name is
# rejected rather than guessed, so the caller can ask the user to pick one
# of these.
EVENT_COLORS: dict[str, str] = {
    "lavender": "1",
    "sage": "2",
    "grape": "3",
    "flamingo": "4",
    "banana": "5",
    "tangerine": "6",
    "peacock": "7",
    "graphite": "8",
    "blueberry": "9",
    "basil": "10",
    "tomato": "11",
}


class CalendarEvent(BaseModel):
    """Internal representation of a Google Calendar event."""

    id: str
    title: str
    start: datetime
    end: datetime
    description: str | None = None
    location: str | None = None
    calendar_name: str | None = None


class FreeBlock(BaseModel):
    """A gap with no scheduled events, within a requested time range."""

    start: datetime
    end: datetime


def load_credentials() -> Credentials:
    """Load a valid credential from the cached token file.

    Non-interactive: refreshes an expired token automatically if a refresh
    token is available, but never launches a browser. Raises
    CalendarServiceError if no usable credential exists - the fix is to run
    scripts/google_calendar_auth.py.
    """
    settings = get_settings()
    token_path = Path(settings.google_calendar_token_file)

    if not token_path.exists():
        raise CalendarServiceError(
            "Google Calendar is not authenticated yet. Run "
            "`uv run python scripts/google_calendar_auth.py` to connect your account."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise CalendarServiceError(
                "Google Calendar authentication has expired and could not be "
                "refreshed. Run `uv run python scripts/google_calendar_auth.py` "
                "again to reconnect your account."
            ) from exc
        token_path.write_text(creds.to_json())
        return creds

    raise CalendarServiceError(
        "Google Calendar credentials are invalid. Run "
        "`uv run python scripts/google_calendar_auth.py` again to reconnect your account."
    )


def _get_client() -> Any:
    """Build an authenticated Google Calendar API client resource."""
    return build("calendar", "v3", credentials=load_credentials())


def _require_timezone_aware(moment: datetime, field_name: str) -> None:
    if moment.tzinfo is None:
        raise CalendarServiceError(f"{field_name} must be a timezone-aware datetime")


def _event_from_api(item: dict[str, Any], calendar_name: str | None = None) -> CalendarEvent:
    start_raw = item["start"].get("dateTime", item["start"].get("date"))
    end_raw = item["end"].get("dateTime", item["end"].get("date"))
    return CalendarEvent(
        id=item["id"],
        title=item.get("summary", "(no title)"),
        start=datetime.fromisoformat(start_raw),
        end=datetime.fromisoformat(end_raw),
        description=item.get("description"),
        location=item.get("location"),
        calendar_name=calendar_name,
    )


def _list_calendars(resource: Any) -> list[dict[str, str]]:
    """Return {id, summary} for every calendar visible to this account
    (main + shared), raising CalendarServiceError if enumeration itself fails."""
    calendars: list[dict[str, str]] = []
    page_token: str | None = None
    try:
        while True:
            response = resource.calendarList().list(pageToken=page_token).execute()
            for item in response.get("items", []):
                calendars.append({"id": item["id"], "summary": item.get("summary", item["id"])})
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        raise CalendarServiceError(f"Failed to list calendars: {exc}") from exc
    return calendars


def _resolve_calendar(resource: Any, calendar_name: str) -> dict[str, str]:
    """Resolve a calendar name to {id, summary} by matching the account's
    calendar list. An exact (case-insensitive) match wins; otherwise a
    unique substring match is used. Raises CalendarServiceError if no
    calendar matches, or if more than one does - never guesses.
    """
    calendars = _list_calendars(resource)
    lowered = calendar_name.strip().lower()

    exact = [c for c in calendars if c["summary"].lower() == lowered]
    if len(exact) == 1:
        return exact[0]

    partial = [c for c in calendars if lowered in c["summary"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(c["summary"] for c in partial)
        raise CalendarServiceError(
            f"'{calendar_name}' matches multiple calendars ({names}) - be more specific."
        )

    available = ", ".join(c["summary"] for c in calendars)
    raise CalendarServiceError(
        f"No calendar found matching '{calendar_name}'. Available calendars: {available}."
    )


def _resolve_color_id(color: str) -> str:
    """Resolve a color name to Google's numeric colorId. Raises
    CalendarServiceError for an unrecognized name - never guesses."""
    color_id = EVENT_COLORS.get(color.strip().lower())
    if color_id is None:
        valid = ", ".join(sorted(EVENT_COLORS))
        raise CalendarServiceError(f"Unknown color '{color}'. Valid colors: {valid}.")
    return color_id


def list_events(
    start: datetime, end: datetime, *, client: Any | None = None
) -> list[CalendarEvent]:
    """List events starting within [start, end] across every calendar visible
    to the account (main + shared), merged and sorted by start time.

    A single calendar that cannot be queried (e.g. a restricted shared
    calendar) is skipped rather than failing the whole request.
    """
    _require_timezone_aware(start, "start")
    _require_timezone_aware(end, "end")
    if end <= start:
        raise CalendarServiceError("end must be after start")

    resource = client if client is not None else _get_client()
    calendars = _list_calendars(resource)

    events: list[CalendarEvent] = []
    for calendar in calendars:
        try:
            response = (
                resource.events()
                .list(
                    calendarId=calendar["id"],
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except HttpError:
            continue
        events.extend(
            _event_from_api(item, calendar_name=calendar["summary"])
            for item in response.get("items", [])
        )

    events.sort(key=lambda event: event.start)
    return events


def list_free_blocks(
    start: datetime, end: datetime, *, client: Any | None = None
) -> list[FreeBlock]:
    """Compute gaps with no scheduled events within [start, end].

    Pure interval arithmetic on top of list_events: overlapping/adjacent
    busy events are merged first (across all calendars), then the
    complement within [start, end] is returned. Deterministic by design -
    this is exactly the kind of exact-interval math an LLM should not be
    trusted to do itself.
    """
    _require_timezone_aware(start, "start")
    _require_timezone_aware(end, "end")
    if end <= start:
        raise CalendarServiceError("end must be after start")

    events = list_events(start, end, client=client)

    busy: list[tuple[datetime, datetime]] = sorted(
        (max(event.start, start), min(event.end, end))
        for event in events
        if event.start < end and event.end > start
    )

    merged: list[tuple[datetime, datetime]] = []
    for busy_start, busy_end in busy:
        if merged and busy_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], busy_end))
        else:
            merged.append((busy_start, busy_end))

    free: list[FreeBlock] = []
    cursor = start
    for busy_start, busy_end in merged:
        if busy_start > cursor:
            free.append(FreeBlock(start=cursor, end=busy_start))
        cursor = max(cursor, busy_end)
    if cursor < end:
        free.append(FreeBlock(start=cursor, end=end))
    return free


def create_event(
    title: str,
    start: datetime,
    end: datetime,
    *,
    description: str | None = None,
    location: str | None = None,
    calendar_name: str | None = None,
    color: str | None = None,
    client: Any | None = None,
) -> CalendarEvent:
    """Create a calendar event. Raises CalendarServiceError if end <= start,
    if calendar_name/color don't resolve, or if the Google API call fails -
    never returns a fabricated event.

    calendar_name selects a specific calendar (main or shared) by name;
    omitted, it defaults to google_calendar_id ("primary"). color must be
    one of EVENT_COLORS' names; there is no custom/personal color support.
    """
    _require_timezone_aware(start, "start")
    _require_timezone_aware(end, "end")
    if end <= start:
        raise CalendarServiceError("end must be after start")

    resource = client if client is not None else _get_client()

    resolved_calendar_name: str | None = None
    if calendar_name is not None:
        resolved = _resolve_calendar(resource, calendar_name)
        calendar_id = resolved["id"]
        resolved_calendar_name = resolved["summary"]
    else:
        calendar_id = get_settings().google_calendar_id

    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if color is not None:
        body["colorId"] = _resolve_color_id(color)

    try:
        created = resource.events().insert(calendarId=calendar_id, body=body).execute()
    except HttpError as exc:
        raise CalendarServiceError(f"Failed to create calendar event: {exc}") from exc

    return _event_from_api(created, calendar_name=resolved_calendar_name)
