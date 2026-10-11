"""Tests for the Calendar + Notion schedule-combining service.

Both underlying services (calendar_service, notion_service) are monkeypatched
at the module level schedule_service imports them under, so these tests
never touch real credentials, the network, or a database.
"""

from datetime import datetime, timedelta, timezone

import pytest

from assistant.services import schedule_service
from assistant.services.calendar_service import FreeBlock
from assistant.services.notion_service import NotionTask

MADRID = timezone(timedelta(hours=2))
START = datetime(2026, 10, 9, 14, 0, tzinfo=MADRID)
END = datetime(2026, 10, 9, 18, 0, tzinfo=MADRID)


def _block(start_hour: int, end_hour: int) -> FreeBlock:
    return FreeBlock(
        start=datetime(2026, 10, 9, start_hour, 0, tzinfo=MADRID),
        end=datetime(2026, 10, 9, end_hour, 0, tzinfo=MADRID),
    )


def _task(task_id: str, *, minutes: int | None, status: str | None = "pending") -> NotionTask:
    return NotionTask(id=task_id, title=f"Task {task_id}", estimated_minutes=minutes, status=status)


def _patch(
    monkeypatch: pytest.MonkeyPatch, free_blocks: list[FreeBlock], tasks: list[NotionTask]
) -> None:
    monkeypatch.setattr(
        schedule_service.calendar_service, "list_free_blocks", lambda *a, **k: free_blocks
    )
    monkeypatch.setattr(schedule_service.notion_service, "list_tasks", lambda *a, **k: tasks)


def test_schedules_single_task_into_free_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, [_block(14, 18)], [_task("t1", minutes=60)])

    schedule = schedule_service.build_schedule(START, END)

    assert len(schedule.scheduled) == 1
    slot = schedule.scheduled[0]
    assert slot.task.id == "t1"
    assert slot.start == datetime(2026, 10, 9, 14, 0, tzinfo=MADRID)
    assert slot.end == datetime(2026, 10, 9, 15, 0, tzinfo=MADRID)
    assert schedule.unscheduled == []


def test_schedules_multiple_tasks_consuming_the_same_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        [_block(14, 18)],
        [_task("t1", minutes=60), _task("t2", minutes=30)],
    )

    schedule = schedule_service.build_schedule(START, END)

    assert [slot.task.id for slot in schedule.scheduled] == ["t1", "t2"]
    assert schedule.scheduled[0].start == datetime(2026, 10, 9, 14, 0, tzinfo=MADRID)
    assert schedule.scheduled[0].end == datetime(2026, 10, 9, 15, 0, tzinfo=MADRID)
    assert schedule.scheduled[1].start == datetime(2026, 10, 9, 15, 0, tzinfo=MADRID)
    assert schedule.scheduled[1].end == datetime(2026, 10, 9, 15, 30, tzinfo=MADRID)


def test_schedules_second_task_into_next_block_when_first_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        [_block(14, 15), _block(16, 17)],
        [_task("t1", minutes=60), _task("t2", minutes=30)],
    )

    schedule = schedule_service.build_schedule(START, END)

    assert schedule.scheduled[0].task.id == "t1"
    assert schedule.scheduled[0].start == datetime(2026, 10, 9, 14, 0, tzinfo=MADRID)
    assert schedule.scheduled[1].task.id == "t2"
    assert schedule.scheduled[1].start == datetime(2026, 10, 9, 16, 0, tzinfo=MADRID)


def test_task_that_does_not_fit_anywhere_is_unscheduled_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, [_block(14, 15)], [_task("t1", minutes=90)])

    schedule = schedule_service.build_schedule(START, END)

    assert schedule.scheduled == []
    assert len(schedule.unscheduled) == 1
    assert schedule.unscheduled[0].task.id == "t1"
    assert schedule.unscheduled[0].reason == "no_free_block_long_enough"


def test_task_with_no_duration_is_unscheduled_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, [_block(14, 18)], [_task("t1", minutes=None)])

    schedule = schedule_service.build_schedule(START, END)

    assert schedule.scheduled == []
    assert len(schedule.unscheduled) == 1
    assert schedule.unscheduled[0].task.id == "t1"
    assert schedule.unscheduled[0].reason == "missing_duration"


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_completed_and_cancelled_tasks_are_excluded_entirely(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """Completed/cancelled tasks are not schedulable at all, so they are
    intentionally excluded from both lists - this is not a gap in the
    "every schedulable task appears exactly once" invariant, since these
    tasks are filtered out before that invariant applies (see
    test_every_schedulable_task_appears_exactly_once_in_scheduled_or_unscheduled)."""
    _patch(monkeypatch, [_block(14, 18)], [_task("t1", minutes=60, status=status)])

    schedule = schedule_service.build_schedule(START, END)

    assert schedule.scheduled == []
    assert schedule.unscheduled == []


def test_every_schedulable_task_appears_exactly_once_in_scheduled_or_unscheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core invariant: across a mix of tasks that fit, don't fit, have
    no duration, and are completed/cancelled, every *schedulable* task
    (i.e. excluding completed/cancelled) appears in exactly one of
    `scheduled` or `unscheduled` - never both, never neither."""
    tasks = [
        _task("fits", minutes=60),
        _task("too_long", minutes=120),
        _task("no_duration", minutes=None),
        _task("done", minutes=30, status="completed"),
        _task("dropped", minutes=30, status="cancelled"),
    ]
    _patch(monkeypatch, [_block(14, 15)], tasks)

    schedule = schedule_service.build_schedule(START, END)

    scheduled_ids = {slot.task.id for slot in schedule.scheduled}
    unscheduled_ids = {entry.task.id for entry in schedule.unscheduled}

    assert scheduled_ids == {"fits"}
    assert unscheduled_ids == {"too_long", "no_duration"}
    # Each schedulable id appears in exactly one of the two sets.
    assert scheduled_ids & unscheduled_ids == set()
    schedulable_ids = {"fits", "too_long", "no_duration"}
    assert scheduled_ids | unscheduled_ids == schedulable_ids
    # Completed/cancelled tasks appear in neither - by design, not a gap.
    assert "done" not in scheduled_ids | unscheduled_ids
    assert "dropped" not in scheduled_ids | unscheduled_ids


def test_no_free_blocks_leaves_every_task_unscheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, [], [_task("t1", minutes=30)])

    schedule = schedule_service.build_schedule(START, END)

    assert schedule.scheduled == []
    assert len(schedule.unscheduled) == 1
    assert schedule.unscheduled[0].task.id == "t1"
    assert schedule.unscheduled[0].reason == "no_free_block_long_enough"


def test_passes_source_through_to_notion_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_list_tasks(**kwargs: object) -> list[NotionTask]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(schedule_service.calendar_service, "list_free_blocks", lambda *a, **k: [])
    monkeypatch.setattr(schedule_service.notion_service, "list_tasks", fake_list_tasks)

    schedule_service.build_schedule(START, END, source="sanofi")

    assert captured["source"] == "sanofi"


def test_build_schedule_never_creates_calendar_events_or_notion_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core safety property: proposing a schedule must have zero side
    effects - it only reads, never writes to either system."""

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_schedule must never call a write operation")

    monkeypatch.setattr(schedule_service.calendar_service, "create_event", fail_if_called)
    monkeypatch.setattr(schedule_service.notion_service, "create_task", fail_if_called)
    monkeypatch.setattr(schedule_service.notion_service, "update_task", fail_if_called)
    _patch(monkeypatch, [_block(14, 18)], [_task("t1", minutes=60)])

    schedule_service.build_schedule(START, END)  # must not raise
