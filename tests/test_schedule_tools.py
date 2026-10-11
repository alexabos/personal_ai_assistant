"""Tests for the propose_schedule tool - no real Calendar/Notion API or LLM
involved.

schedule_service.build_schedule is monkeypatched so these tests isolate
argument translation and result shaping, the tool's own responsibility,
from the service (already covered by test_schedule_service.py).
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from assistant.services.notion_service import NotionTask
from assistant.services.schedule_service import ProposedSchedule, ScheduledSlot
from assistant.tools import schedule_tools
from assistant.tools.schedule_tools import ProposeScheduleArgs, propose_schedule

MADRID = timezone(timedelta(hours=2))
START = datetime(2026, 10, 9, 14, 0, tzinfo=MADRID)
END = datetime(2026, 10, 9, 18, 0, tzinfo=MADRID)


def test_propose_schedule_passes_args_and_shapes_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_build_schedule(start: datetime, end: datetime, **kwargs: object) -> ProposedSchedule:
        captured["start"] = start
        captured["end"] = end
        captured.update(kwargs)
        task = NotionTask(id="t1", title="Task", estimated_minutes=60, source="sanofi")
        slot = ScheduledSlot(start=start, end=start + timedelta(minutes=60), task=task)
        return ProposedSchedule(
            range_start=start, range_end=end, scheduled=[slot], unscheduled=[]
        )

    monkeypatch.setattr(schedule_tools.schedule_service, "build_schedule", fake_build_schedule)

    args = ProposeScheduleArgs(start_datetime=START, end_datetime=END, source="sanofi")
    result = propose_schedule(None, args)

    assert captured["start"] == START
    assert captured["end"] == END
    assert captured["source"] == "sanofi"
    assert result["scheduled"][0]["task"]["id"] == "t1"
    assert result["unscheduled"] == []


def test_propose_schedule_default_source_is_all() -> None:
    args = ProposeScheduleArgs(start_datetime=START, end_datetime=END)
    assert args.source == "all"


def test_propose_schedule_args_reject_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        ProposeScheduleArgs(start_datetime=datetime(2026, 10, 9, 14, 0), end_datetime=END)


def test_propose_schedule_args_reject_backwards_range() -> None:
    with pytest.raises(ValidationError):
        ProposeScheduleArgs(start_datetime=END, end_datetime=START)
