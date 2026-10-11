"""Combines Google Calendar free time with Notion tasks into a proposed
schedule.

Framework-agnostic by design: see task_service.py for the rationale. Plays
the same cross-system-combiner role for calendar_service + notion_service
that planning_service already plays for task_service + weekly_goal_service -
each underlying service stays single-system; this is where they meet.

This only ever proposes a schedule - it has no way to create calendar
events and never calls calendar_service.create_event. Committing a proposal
to the real calendar is a separate, explicit action the LLM takes only if
the user asks for it afterward (see agent/orchestrator.py's system prompt).

Deterministic by design, consistent with planning_service: free/busy gaps
and task ranking are exact facts, computed in Python - not left to the LLM
to estimate or re-derive.
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from assistant.services import calendar_service, notion_service
from assistant.services.notion_service import NotionTask

# Completed/cancelled tasks are not schedulable at all: they are excluded
# before the scheduling loop runs and never appear in `scheduled` or
# `unscheduled` - this is intentional and is not a gap in the invariant
# below, which only applies to schedulable tasks.
_UNSCHEDULABLE_STATUSES = {"completed", "cancelled"}

UnscheduledReason = Literal["missing_duration", "no_free_block_long_enough"]


class ScheduledSlot(BaseModel):
    """One task proposed to fill part of a free block."""

    start: datetime
    end: datetime
    task: NotionTask


class UnscheduledTask(BaseModel):
    """A schedulable task that could not be placed, and why.

    The reason belongs here, on the scheduling result, rather than on
    NotionTask itself - it describes an outcome of this scheduling attempt,
    not a property of the task.
    """

    task: NotionTask
    reason: UnscheduledReason


class ProposedSchedule(BaseModel):
    """A draft schedule.

    Every *schedulable* task (i.e. not completed or cancelled) appears
    exactly once, in either `scheduled` or `unscheduled` (with a reason) -
    never silently dropped. Completed/cancelled tasks are excluded from
    consideration entirely before this invariant applies; they are not
    schedulable and intentionally do not appear in either list.
    """

    range_start: datetime
    range_end: datetime
    scheduled: list[ScheduledSlot]
    unscheduled: list[UnscheduledTask]


def build_schedule(
    start: datetime,
    end: datetime,
    *,
    source: str = "all",
    calendar_client: object | None = None,
    notion_client: object | None = None,
) -> ProposedSchedule:
    """Propose a schedule for [start, end]: rank actionable Notion tasks
    (already sorted by deadline then priority) and greedily place each one
    into the first free Calendar block with enough room for its full
    estimated_minutes - never splitting a task across two blocks.

    Every schedulable task (not completed/cancelled) ends up in exactly one
    of `scheduled` or `unscheduled` - a task with no duration, or that
    doesn't fit in any remaining free time, is returned in `unscheduled`
    with a reason, rather than being dropped. Raises
    CalendarServiceError/NotionServiceError if either underlying source
    cannot be read - never returns a schedule built on partial data.
    """
    free_blocks = calendar_service.list_free_blocks(start, end, client=calendar_client)
    tasks = notion_service.list_tasks(source=source, client=notion_client)

    remaining: list[tuple[datetime, datetime]] = [(b.start, b.end) for b in free_blocks]

    scheduled: list[ScheduledSlot] = []
    unscheduled: list[UnscheduledTask] = []

    for task in tasks:
        if task.status in _UNSCHEDULABLE_STATUSES:
            continue
        if task.estimated_minutes is None:
            unscheduled.append(UnscheduledTask(task=task, reason="missing_duration"))
            continue

        placed = False
        for index, (block_start, block_end) in enumerate(remaining):
            available_minutes = (block_end - block_start).total_seconds() / 60
            if available_minutes >= task.estimated_minutes:
                slot_end = block_start + timedelta(minutes=task.estimated_minutes)
                scheduled.append(ScheduledSlot(start=block_start, end=slot_end, task=task))
                remaining[index] = (slot_end, block_end)
                placed = True
                break

        if not placed:
            unscheduled.append(
                UnscheduledTask(task=task, reason="no_free_block_long_enough")
            )

    return ProposedSchedule(
        range_start=start, range_end=end, scheduled=scheduled, unscheduled=unscheduled
    )
