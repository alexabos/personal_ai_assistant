"""Tests for the Google Calendar service.

The Google API resource is always injected via the `client` parameter, so
these tests never touch real credentials or the network - calendar_service's
only credential-reading function (load_credentials, used by _get_client) is
never called here.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from assistant.services.calendar_service import create_event, list_events, list_free_blocks
from assistant.services.errors import CalendarServiceError

MADRID = timezone(timedelta(hours=2))  # CEST offset, explicit for test clarity
START = datetime(2026, 9, 24, 9, 0, tzinfo=MADRID)
END = datetime(2026, 9, 24, 18, 0, tzinfo=MADRID)


def _mock_resource_for_listing(
    calendars: list[dict], events_by_calendar: dict[str, dict] | None = None
) -> MagicMock:
    """A mock resource whose calendarList().list() and events().list() return
    per-calendar data, mirroring how list_events() queries each calendar it
    discovers."""
    resource = MagicMock()
    resource.calendarList.return_value.list.return_value.execute.return_value = {
        "items": calendars
    }

    events_by_calendar = events_by_calendar or {}

    def list_side_effect(calendarId: str, **kwargs: object) -> MagicMock:
        call = MagicMock()
        payload = events_by_calendar.get(calendarId)
        if isinstance(payload, Exception):
            call.execute.side_effect = payload
        else:
            call.execute.return_value = payload or {"items": []}
        return call

    resource.events.return_value.list.side_effect = list_side_effect
    return resource


def _mock_resource_for_creating(result: dict, calendars: list[dict] | None = None) -> MagicMock:
    resource = MagicMock()
    resource.events.return_value.insert.return_value.execute.return_value = result
    if calendars is not None:
        resource.calendarList.return_value.list.return_value.execute.return_value = {
            "items": calendars
        }
    return resource


def test_list_events_returns_mapped_events() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {
                "items": [
                    {
                        "id": "abc123",
                        "summary": "Team meeting",
                        "start": {"dateTime": "2026-09-24T10:00:00+02:00"},
                        "end": {"dateTime": "2026-09-24T11:00:00+02:00"},
                        "description": "Weekly sync",
                        "location": "Office",
                    }
                ]
            }
        },
    )

    events = list_events(START, END, client=resource)

    assert len(events) == 1
    event = events[0]
    assert event.id == "abc123"
    assert event.title == "Team meeting"
    assert event.description == "Weekly sync"
    assert event.location == "Office"
    assert event.calendar_name == "Main"
    assert event.start.tzinfo is not None


def test_list_events_merges_and_sorts_across_calendars() -> None:
    resource = _mock_resource_for_listing(
        calendars=[
            {"id": "primary", "summary": "Main"},
            {"id": "shared@group.calendar.google.com", "summary": "Team"},
        ],
        events_by_calendar={
            "primary": {
                "items": [
                    {
                        "id": "later",
                        "summary": "Later event",
                        "start": {"dateTime": "2026-09-24T16:00:00+02:00"},
                        "end": {"dateTime": "2026-09-24T17:00:00+02:00"},
                    }
                ]
            },
            "shared@group.calendar.google.com": {
                "items": [
                    {
                        "id": "earlier",
                        "summary": "Earlier event",
                        "start": {"dateTime": "2026-09-24T09:30:00+02:00"},
                        "end": {"dateTime": "2026-09-24T10:00:00+02:00"},
                    }
                ]
            },
        },
    )

    events = list_events(START, END, client=resource)

    assert [event.id for event in events] == ["earlier", "later"]
    assert events[0].calendar_name == "Team"
    assert events[1].calendar_name == "Main"


def test_list_events_skips_calendar_that_fails_without_failing_others() -> None:
    error = HttpError(httplib2.Response({"status": "403"}), b"Insufficient Permission")
    resource = _mock_resource_for_listing(
        calendars=[
            {"id": "primary", "summary": "Main"},
            {"id": "restricted", "summary": "Restricted"},
        ],
        events_by_calendar={
            "primary": {
                "items": [
                    {
                        "id": "ok-event",
                        "summary": "Visible event",
                        "start": {"dateTime": "2026-09-24T10:00:00+02:00"},
                        "end": {"dateTime": "2026-09-24T11:00:00+02:00"},
                    }
                ]
            },
            "restricted": error,
        },
    )

    events = list_events(START, END, client=resource)

    assert [event.id for event in events] == ["ok-event"]


def test_list_events_handles_empty_result() -> None:
    resource = _mock_resource_for_listing(calendars=[{"id": "primary", "summary": "Main"}])

    events = list_events(START, END, client=resource)

    assert events == []


def test_list_events_rejects_naive_start() -> None:
    naive_start = datetime(2026, 9, 24, 9, 0)

    with pytest.raises(CalendarServiceError):
        list_events(naive_start, END, client=MagicMock())


def test_list_events_rejects_invalid_range() -> None:
    with pytest.raises(CalendarServiceError):
        list_events(END, START, client=MagicMock())


def test_list_events_wraps_calendar_enumeration_error() -> None:
    resource = MagicMock()
    error = HttpError(httplib2.Response({"status": "403"}), b"Insufficient Permission")
    resource.calendarList.return_value.list.return_value.execute.side_effect = error

    with pytest.raises(CalendarServiceError):
        list_events(START, END, client=resource)


def test_create_event_returns_created_event() -> None:
    resource = _mock_resource_for_creating(
        {
            "id": "new-event-1",
            "summary": "Dentist appointment",
            "start": {"dateTime": "2026-09-28T16:00:00+02:00"},
            "end": {"dateTime": "2026-09-28T17:00:00+02:00"},
        }
    )

    event = create_event(
        "Dentist appointment",
        datetime(2026, 9, 28, 16, 0, tzinfo=MADRID),
        datetime(2026, 9, 28, 17, 0, tzinfo=MADRID),
        client=resource,
    )

    assert event.id == "new-event-1"
    assert event.title == "Dentist appointment"


def test_create_event_rejects_invalid_range() -> None:
    with pytest.raises(CalendarServiceError):
        create_event("Backwards event", END, START, client=MagicMock())


def test_create_event_rejects_naive_datetimes() -> None:
    with pytest.raises(CalendarServiceError):
        create_event(
            "Naive event",
            datetime(2026, 9, 24, 9, 0),
            datetime(2026, 9, 24, 10, 0),
            client=MagicMock(),
        )


def test_create_event_wraps_google_api_error() -> None:
    resource = MagicMock()
    error = HttpError(httplib2.Response({"status": "500"}), b"Internal Server Error")
    resource.events.return_value.insert.return_value.execute.side_effect = error

    with pytest.raises(CalendarServiceError):
        create_event("Meeting", START, END, client=resource)


def test_create_event_resolves_calendar_by_exact_name() -> None:
    resource = _mock_resource_for_creating(
        {
            "id": "new-event-2",
            "summary": "Gym",
            "start": {"dateTime": "2026-10-09T08:00:00+02:00"},
            "end": {"dateTime": "2026-10-09T09:00:00+02:00"},
        },
        calendars=[
            {"id": "primary", "summary": "Main"},
            {"id": "shared@group.calendar.google.com", "summary": "Família Rodes Abos"},
        ],
    )

    event = create_event(
        "Gym",
        datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
        datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
        calendar_name="Família Rodes Abos",
        client=resource,
    )

    resource.events.return_value.insert.assert_called_once()
    _, kwargs = resource.events.return_value.insert.call_args
    assert kwargs["calendarId"] == "shared@group.calendar.google.com"
    assert event.calendar_name == "Família Rodes Abos"


def test_create_event_resolves_calendar_by_partial_name() -> None:
    resource = _mock_resource_for_creating(
        {
            "id": "new-event-3",
            "summary": "Gym",
            "start": {"dateTime": "2026-10-09T08:00:00+02:00"},
            "end": {"dateTime": "2026-10-09T09:00:00+02:00"},
        },
        calendars=[
            {"id": "primary", "summary": "Main"},
            {"id": "shared@group.calendar.google.com", "summary": "Família Rodes Abos"},
        ],
    )

    create_event(
        "Gym",
        datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
        datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
        calendar_name="família",
        client=resource,
    )

    _, kwargs = resource.events.return_value.insert.call_args
    assert kwargs["calendarId"] == "shared@group.calendar.google.com"


def test_create_event_raises_when_calendar_name_not_found() -> None:
    resource = _mock_resource_for_creating(
        {},
        calendars=[{"id": "primary", "summary": "Main"}],
    )

    with pytest.raises(CalendarServiceError):
        create_event(
            "Gym",
            datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
            datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
            calendar_name="Nonexistent calendar",
            client=resource,
        )
    resource.events.return_value.insert.assert_not_called()


def test_create_event_raises_when_calendar_name_ambiguous() -> None:
    resource = _mock_resource_for_creating(
        {},
        calendars=[
            {"id": "cal1", "summary": "Family A"},
            {"id": "cal2", "summary": "Family B"},
        ],
    )

    with pytest.raises(CalendarServiceError):
        create_event(
            "Gym",
            datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
            datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
            calendar_name="Family",
            client=resource,
        )


def test_create_event_sets_color_id() -> None:
    resource = _mock_resource_for_creating(
        {
            "id": "new-event-4",
            "summary": "Gym",
            "start": {"dateTime": "2026-10-09T08:00:00+02:00"},
            "end": {"dateTime": "2026-10-09T09:00:00+02:00"},
        }
    )

    create_event(
        "Gym",
        datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
        datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
        color="Tomato",
        client=resource,
    )

    _, kwargs = resource.events.return_value.insert.call_args
    assert kwargs["body"]["colorId"] == "11"


def test_create_event_raises_on_unknown_color() -> None:
    resource = _mock_resource_for_creating({})

    with pytest.raises(CalendarServiceError):
        create_event(
            "Gym",
            datetime(2026, 10, 9, 8, 0, tzinfo=MADRID),
            datetime(2026, 10, 9, 9, 0, tzinfo=MADRID),
            color="Alexandra",
            client=resource,
        )
    resource.events.return_value.insert.assert_not_called()


# --- Free/busy ---------------------------------------------------------------


def _event_item(event_id: str, start_iso: str, end_iso: str) -> dict:
    return {
        "id": event_id,
        "summary": "Busy",
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }


def test_list_free_blocks_whole_range_free_when_no_events() -> None:
    resource = _mock_resource_for_listing(calendars=[{"id": "primary", "summary": "Main"}])

    blocks = list_free_blocks(START, END, client=resource)

    assert len(blocks) == 1
    assert blocks[0].start == START
    assert blocks[0].end == END


def test_list_free_blocks_splits_around_single_event() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {
                "items": [
                    _event_item(
                        "e1", "2026-09-24T12:00:00+02:00", "2026-09-24T13:00:00+02:00"
                    )
                ]
            }
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    assert len(blocks) == 2
    assert blocks[0].start == START
    assert blocks[0].end == datetime(2026, 9, 24, 12, 0, tzinfo=MADRID)
    assert blocks[1].start == datetime(2026, 9, 24, 13, 0, tzinfo=MADRID)
    assert blocks[1].end == END


def test_list_free_blocks_merges_overlapping_events() -> None:
    resource = _mock_resource_for_listing(
        calendars=[
            {"id": "primary", "summary": "Main"},
            {"id": "shared", "summary": "Shared"},
        ],
        events_by_calendar={
            "primary": {
                "items": [
                    _event_item(
                        "e1", "2026-09-24T12:00:00+02:00", "2026-09-24T13:00:00+02:00"
                    )
                ]
            },
            "shared": {
                "items": [
                    _event_item(
                        "e2", "2026-09-24T12:30:00+02:00", "2026-09-24T14:00:00+02:00"
                    )
                ]
            },
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    # Overlapping 12:00-13:00 and 12:30-14:00 merge into one 12:00-14:00 busy
    # block, leaving two free blocks either side of it.
    assert len(blocks) == 2
    assert blocks[0].end == datetime(2026, 9, 24, 12, 0, tzinfo=MADRID)
    assert blocks[1].start == datetime(2026, 9, 24, 14, 0, tzinfo=MADRID)


def test_list_free_blocks_no_gap_for_back_to_back_events() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {
                "items": [
                    _event_item(
                        "e1", "2026-09-24T12:00:00+02:00", "2026-09-24T13:00:00+02:00"
                    ),
                    _event_item(
                        "e2", "2026-09-24T13:00:00+02:00", "2026-09-24T14:00:00+02:00"
                    ),
                ]
            }
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    assert len(blocks) == 2
    assert blocks[0].end == datetime(2026, 9, 24, 12, 0, tzinfo=MADRID)
    assert blocks[1].start == datetime(2026, 9, 24, 14, 0, tzinfo=MADRID)


def test_list_free_blocks_ignores_events_outside_range() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {
                "items": [
                    _event_item(
                        "e1", "2026-09-24T06:00:00+02:00", "2026-09-24T08:00:00+02:00"
                    )
                ]
            }
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    assert len(blocks) == 1
    assert blocks[0].start == START
    assert blocks[0].end == END


def test_list_free_blocks_clips_event_crossing_range_boundary() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {
                "items": [
                    _event_item(
                        "e1", "2026-09-24T08:00:00+02:00", "2026-09-24T10:00:00+02:00"
                    )
                ]
            }
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    assert len(blocks) == 1
    assert blocks[0].start == datetime(2026, 9, 24, 10, 0, tzinfo=MADRID)
    assert blocks[0].end == END


def test_list_free_blocks_fully_busy_returns_no_blocks() -> None:
    resource = _mock_resource_for_listing(
        calendars=[{"id": "primary", "summary": "Main"}],
        events_by_calendar={
            "primary": {"items": [_event_item("e1", START.isoformat(), END.isoformat())]}
        },
    )

    blocks = list_free_blocks(START, END, client=resource)

    assert blocks == []


def test_list_free_blocks_rejects_invalid_range() -> None:
    with pytest.raises(CalendarServiceError):
        list_free_blocks(END, START, client=MagicMock())


def test_list_free_blocks_rejects_naive_datetime() -> None:
    with pytest.raises(CalendarServiceError):
        list_free_blocks(datetime(2026, 9, 24, 9, 0), END, client=MagicMock())
