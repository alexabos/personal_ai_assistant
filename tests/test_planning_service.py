"""Tests for the deterministic planning service.

All tests inject an explicit `today` so results never depend on the real
wall-clock date (same pattern used for MONDAY/NEXT_MONDAY in
test_weekly_goals.py).
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from assistant.db.models import TaskPriority
from assistant.services import planning_service, task_service, weekly_goal_service

TODAY = date(2026, 9, 16)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def test_list_overdue_tasks_includes_only_tasks_due_before_today(db_session: Session) -> None:
    overdue = task_service.create_task(db_session, title="Overdue", due_date=YESTERDAY)
    task_service.create_task(db_session, title="Due today", due_date=TODAY)
    task_service.create_task(db_session, title="Due tomorrow", due_date=TOMORROW)
    task_service.create_task(db_session, title="No due date")

    result = planning_service.list_overdue_tasks(db_session, today=TODAY)

    assert [task.id for task in result] == [overdue.id]


def test_list_relevant_tasks_includes_overdue_and_due_today(db_session: Session) -> None:
    overdue = task_service.create_task(db_session, title="Overdue", due_date=YESTERDAY)
    due_today = task_service.create_task(db_session, title="Due today", due_date=TODAY)
    task_service.create_task(db_session, title="Due tomorrow", due_date=TOMORROW)

    result = planning_service.list_relevant_tasks(db_session, today=TODAY)

    ids = {task.id for task in result}
    assert ids == {overdue.id, due_today.id}


def test_cancelled_task_excluded_from_overdue(db_session: Session) -> None:
    task = task_service.create_task(db_session, title="Overdue", due_date=YESTERDAY)
    task_service.cancel_task(db_session, task.id)

    result = planning_service.list_overdue_tasks(db_session, today=TODAY)

    assert result == []


def test_completed_task_excluded_from_overdue(db_session: Session) -> None:
    task = task_service.create_task(db_session, title="Overdue", due_date=YESTERDAY)
    task_service.complete_task(db_session, task.id)

    result = planning_service.list_overdue_tasks(db_session, today=TODAY)

    assert result == []


def test_goal_behind_pace_is_flagged(db_session: Session) -> None:
    goal = weekly_goal_service.create_weekly_goal(
        db_session, title="Goal", week_start=MONDAY, target_minutes=140
    )

    result = planning_service.list_goals_falling_behind(
        db_session, today=MONDAY + timedelta(days=3)
    )

    assert [g.id for g in result] == [goal.id]


def test_goal_on_pace_is_not_flagged(db_session: Session) -> None:
    goal = weekly_goal_service.create_weekly_goal(
        db_session, title="Goal", week_start=MONDAY, target_minutes=140
    )
    weekly_goal_service.update_weekly_goal(db_session, goal.id, completed_minutes=100)

    result = planning_service.list_goals_falling_behind(
        db_session, today=MONDAY + timedelta(days=3)
    )

    assert result == []


def test_goal_without_target_minutes_is_skipped(db_session: Session) -> None:
    weekly_goal_service.create_weekly_goal(db_session, title="Goal", week_start=MONDAY)

    result = planning_service.list_goals_falling_behind(
        db_session, today=MONDAY + timedelta(days=3)
    )

    assert result == []


def test_goal_outside_current_week_is_skipped(db_session: Session) -> None:
    last_week = MONDAY - timedelta(days=7)
    weekly_goal_service.create_weekly_goal(
        db_session, title="Last week goal", week_start=last_week, target_minutes=100
    )
    next_week = MONDAY + timedelta(days=7)
    weekly_goal_service.create_weekly_goal(
        db_session, title="Next week goal", week_start=next_week, target_minutes=100
    )

    result = planning_service.list_goals_falling_behind(db_session, today=MONDAY)

    assert result == []


def test_cancelled_goal_is_never_flagged(db_session: Session) -> None:
    goal = weekly_goal_service.create_weekly_goal(
        db_session, title="Goal", week_start=MONDAY, target_minutes=140
    )
    weekly_goal_service.cancel_weekly_goal(db_session, goal.id)

    result = planning_service.list_goals_falling_behind(
        db_session, today=MONDAY + timedelta(days=3)
    )

    assert result == []


def test_suggest_next_task_prefers_overdue_high_priority(db_session: Session) -> None:
    task_service.create_task(
        db_session,
        title="Low priority, due tomorrow",
        priority=TaskPriority.LOW,
        due_date=TOMORROW,
    )
    urgent = task_service.create_task(
        db_session,
        title="High priority, overdue",
        priority=TaskPriority.HIGH,
        due_date=YESTERDAY,
    )

    result = planning_service.suggest_next_task(db_session, today=TODAY)

    assert result is not None
    assert result.id == urgent.id


def test_suggest_next_task_respects_available_minutes(db_session: Session) -> None:
    task_service.create_task(
        db_session,
        title="High priority, too long",
        priority=TaskPriority.HIGH,
        estimated_minutes=60,
    )
    fits = task_service.create_task(
        db_session,
        title="Low priority, fits",
        priority=TaskPriority.LOW,
        estimated_minutes=30,
    )

    result = planning_service.suggest_next_task(db_session, available_minutes=45, today=TODAY)

    assert result is not None
    assert result.id == fits.id


def test_suggest_next_task_excludes_unknown_duration_when_minutes_given(
    db_session: Session,
) -> None:
    task_service.create_task(db_session, title="Unknown duration")

    result = planning_service.suggest_next_task(db_session, available_minutes=30, today=TODAY)

    assert result is None


def test_suggest_next_task_includes_unknown_duration_when_no_minutes_given(
    db_session: Session,
) -> None:
    task = task_service.create_task(db_session, title="Unknown duration")

    result = planning_service.suggest_next_task(db_session, today=TODAY)

    assert result is not None
    assert result.id == task.id


def test_suggest_next_task_returns_none_when_no_candidates(db_session: Session) -> None:
    result = planning_service.suggest_next_task(db_session, today=TODAY)

    assert result is None


def test_build_daily_plan_aggregates_all_pieces(db_session: Session) -> None:
    overdue = task_service.create_task(
        db_session, title="Overdue", due_date=YESTERDAY, estimated_minutes=30
    )
    weekly_goal_service.create_weekly_goal(
        db_session, title="Goal", week_start=MONDAY, target_minutes=140
    )

    plan = planning_service.build_daily_plan(
        db_session, available_minutes=45, today=MONDAY + timedelta(days=3)
    )

    assert plan.reference_date == MONDAY + timedelta(days=3)
    assert overdue.id in {task.id for task in plan.overdue_tasks}
    assert len(plan.goals_falling_behind) == 1
    assert plan.suggested_task is not None
    assert plan.suggested_task.id == overdue.id
