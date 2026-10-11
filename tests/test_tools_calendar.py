"""Tests for the calendar tools - no real Google API or LLM involved.

calendar_service functions are monkeypatched so these tests isolate argument
translation and result shaping, the tool's own responsibility, from the
service (already covered by test_calendar_service.py).
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from assistant.services.calendar_service import CalendarEvent, FreeBlock
from assistant.services.errors import CalendarServiceError
from assistant.tools import calendar_tools
from assistant.tools.calendar_tools import (
    CreateCalendarEventArgs,
    ListCalendarEventsArgs,
    create_calendar_event,
    list_calendar_events,
    list_free_time,
)

MADRID = timezone(timedelta(hours=2))
START = datetime(2026, 9, 24, 0, 0, tzinfo=MADRID)
END = datetime(2026, 9, 25, 0, 0, tzinfo=MADRID)


def test_list_calendar_events_passes_args_and_shapes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_list_events(start: datetime, end: datetime, **kwargs: object) -> list[CalendarEvent]:
        captured["start"] = start
        captured["end"] = end
        return [CalendarEvent(id="1", title="Meeting", start=start, end=end)]

    monkeypatch.setattr(calendar_tools.calendar_service, "list_events", fake_list_events)

    args = ListCalendarEventsArgs(start_datetime=START, end_datetime=END)
    result = list_calendar_events(None, args)

    assert captured["start"] == START
    assert captured["end"] == END
    assert result["events"][0]["title"] == "Meeting"


def test_list_free_time_passes_args_and_shapes_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_list_free_blocks(start: datetime, end: datetime, **kwargs: object) -> list[FreeBlock]:
        captured["start"] = start
        captured["end"] = end
        return [FreeBlock(start=start, end=end)]

    monkeypatch.setattr(calendar_tools.calendar_service, "list_free_blocks", fake_list_free_blocks)

    args = ListCalendarEventsArgs(start_datetime=START, end_datetime=END)
    result = list_free_time(None, args)

    assert captured["start"] == START
    assert captured["end"] == END
    assert result["free_blocks"][0]["start"] == START.isoformat()
    assert result["free_blocks"][0]["end"] == END.isoformat()


def test_list_free_time_propagates_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list_free_blocks(*args: object, **kwargs: object) -> list[FreeBlock]:
        raise CalendarServiceError("boom")

    monkeypatch.setattr(calendar_tools.calendar_service, "list_free_blocks", fake_list_free_blocks)

    with pytest.raises(CalendarServiceError):
        list_free_time(None, ListCalendarEventsArgs(start_datetime=START, end_datetime=END))


def test_list_calendar_events_propagates_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list_events(*args: object, **kwargs: object) -> list[CalendarEvent]:
        raise CalendarServiceError("boom")

    monkeypatch.setattr(calendar_tools.calendar_service, "list_events", fake_list_events)

    with pytest.raises(CalendarServiceError):
        list_calendar_events(None, ListCalendarEventsArgs(start_datetime=START, end_datetime=END))


def test_list_calendar_events_args_reject_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        ListCalendarEventsArgs(start_datetime=datetime(2026, 9, 24, 0, 0), end_datetime=END)


def test_list_calendar_events_args_reject_backwards_range() -> None:
    with pytest.raises(ValidationError):
        ListCalendarEventsArgs(start_datetime=END, end_datetime=START)


def test_create_calendar_event_passes_args_and_shapes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_create_event(
        title: str, start: datetime, end: datetime, **kwargs: object
    ) -> CalendarEvent:
        captured["title"] = title
        captured["description"] = kwargs.get("description")
        captured["location"] = kwargs.get("location")
        captured["calendar_name"] = kwargs.get("calendar_name")
        captured["color"] = kwargs.get("color")
        return CalendarEvent(id="new-1", title=title, start=start, end=end)

    monkeypatch.setattr(calendar_tools.calendar_service, "create_event", fake_create_event)

    args = CreateCalendarEventArgs(
        title="Dentist",
        start_datetime=START,
        end_datetime=END,
        description="Checkup",
        location="Clinic",
        calendar_name="Família Rodes Abos",
        color="Tomato",
    )
    result = create_calendar_event(None, args)

    assert captured["title"] == "Dentist"
    assert captured["description"] == "Checkup"
    assert captured["location"] == "Clinic"
    assert captured["calendar_name"] == "Família Rodes Abos"
    assert captured["color"] == "Tomato"
    assert result["status"] == "created"
    assert result["event"]["id"] == "new-1"


def test_create_calendar_event_does_not_report_success_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_event(*args: object, **kwargs: object) -> CalendarEvent:
        raise CalendarServiceError("Google API unavailable")

    monkeypatch.setattr(calendar_tools.calendar_service, "create_event", fake_create_event)

    args = CreateCalendarEventArgs(title="Meeting", start_datetime=START, end_datetime=END)
    with pytest.raises(CalendarServiceError):
        create_calendar_event(None, args)


def test_create_calendar_event_args_reject_empty_title() -> None:
    with pytest.raises(ValidationError):
        CreateCalendarEventArgs(title="   ", start_datetime=START, end_datetime=END)


def test_create_calendar_event_args_reject_backwards_range() -> None:
    with pytest.raises(ValidationError):
        CreateCalendarEventArgs(title="Meeting", start_datetime=END, end_datetime=START)


def test_create_calendar_event_args_reject_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        CreateCalendarEventArgs(
            title="Meeting", start_datetime=datetime(2026, 9, 24, 9, 0), end_datetime=END
        )


def test_create_calendar_event_args_accept_known_color_case_insensitively() -> None:
    args = CreateCalendarEventArgs(
        title="Meeting", start_datetime=START, end_datetime=END, color="TOMATO"
    )
    assert args.color == "TOMATO"


def test_create_calendar_event_args_reject_unknown_color() -> None:
    with pytest.raises(ValidationError):
        CreateCalendarEventArgs(
            title="Meeting", start_datetime=START, end_datetime=END, color="Alexandra"
        )
