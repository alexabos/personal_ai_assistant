"""Deterministic planning and recommendation logic.

Framework-agnostic by design: see task_service.py for the rationale. This
module builds on top of task_service and weekly_goal_service rather than
querying the database directly — it reuses their existing filtering/lifecycle
rules instead of duplicating SQL, and adds planning-specific interpretation
(overdue detection, pace tracking, ranking) as pure Python on top.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from assistant.db.models import Task, TaskPriority, TaskStatus, WeeklyGoal, WeeklyGoalStatus
from assistant.services import task_service, weekly_goal_service

_PRIORITY_RANK: dict[TaskPriority, int] = {
    TaskPriority.HIGH: 0,
    TaskPriority.MEDIUM: 1,
    TaskPriority.LOW: 2,
}


@dataclass(frozen=True)
class DailyPlan:
    """An aggregated planning snapshot for a given reference date."""

    reference_date: date
    relevant_tasks: list[Task]
    overdue_tasks: list[Task]
    goals_falling_behind: list[WeeklyGoal]
    suggested_task: Task | None


def _active_tasks(db: Session) -> list[Task]:
    """Return tasks that are still actionable (not completed, not cancelled)."""
    tasks = task_service.list_tasks(db, include_completed=False)
    return [task for task in tasks if task.status != TaskStatus.CANCELLED]


def list_overdue_tasks(db: Session, *, today: date | None = None) -> list[Task]:
    """Return active tasks whose due date is before today."""
    resolved_today = today or date.today()
    return [
        task
        for task in _active_tasks(db)
        if task.due_date is not None and task.due_date < resolved_today
    ]


def list_relevant_tasks(db: Session, *, today: date | None = None) -> list[Task]:
    """Return active tasks due today or overdue."""
    resolved_today = today or date.today()
    return [
        task
        for task in _active_tasks(db)
        if task.due_date is not None and task.due_date <= resolved_today
    ]


def list_goals_falling_behind(db: Session, *, today: date | None = None) -> list[WeeklyGoal]:
    """Return active goals, currently within their target week, behind a constant pace.

    A goal with no target_minutes is skipped: there is no pace to measure it
    against. No tolerance is applied - any shortfall counts as behind.
    """
    resolved_today = today or date.today()
    goals = weekly_goal_service.list_weekly_goals(db, status=WeeklyGoalStatus.ACTIVE)
    behind: list[WeeklyGoal] = []
    for goal in goals:
        if goal.target_minutes is None:
            continue
        week_end = goal.week_start + timedelta(days=6)
        if not (goal.week_start <= resolved_today <= week_end):
            continue
        elapsed_days = max(0, min((resolved_today - goal.week_start).days + 1, 7))
        expected_minutes = goal.target_minutes * elapsed_days / 7
        if goal.completed_minutes < expected_minutes:
            behind.append(goal)
    return behind


def _fits_time_budget(task: Task, available_minutes: int | None) -> bool:
    """Whether a task can be picked given an optional time budget.

    If no budget is given, a task with an unknown duration is still eligible.
    If a budget is given, a task with an unknown duration is excluded: we
    cannot assume it fits just because we don't know how long it takes.
    """
    if available_minutes is None:
        return True
    return task.estimated_minutes is not None and task.estimated_minutes <= available_minutes


def _suggestion_sort_key(task: Task, today: date) -> tuple[bool, int, date, datetime]:
    """Rank overdue first, then by priority, then by soonest due date, then oldest first."""
    is_overdue = task.due_date is not None and task.due_date < today
    return (
        not is_overdue,
        _PRIORITY_RANK[task.priority],
        task.due_date or date.max,
        task.created_at,
    )


def suggest_next_task(
    db: Session, *, available_minutes: int | None = None, today: date | None = None
) -> Task | None:
    """Suggest the single best task to work on next, or None if nothing qualifies."""
    resolved_today = today or date.today()
    candidates = [
        task for task in _active_tasks(db) if _fits_time_budget(task, available_minutes)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda task: _suggestion_sort_key(task, resolved_today))


def build_daily_plan(
    db: Session, *, available_minutes: int | None = None, today: date | None = None
) -> DailyPlan:
    """Build the full planning snapshot for a given reference date."""
    resolved_today = today or date.today()
    return DailyPlan(
        reference_date=resolved_today,
        relevant_tasks=list_relevant_tasks(db, today=resolved_today),
        overdue_tasks=list_overdue_tasks(db, today=resolved_today),
        goals_falling_behind=list_goals_falling_behind(db, today=resolved_today),
        suggested_task=suggest_next_task(
            db, available_minutes=available_minutes, today=resolved_today
        ),
    )
