"""Tests for the get_daily_plan tool - no LLM involved."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from assistant.services import task_service
from assistant.tools.planning_tools import GetDailyPlanArgs, get_daily_plan

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def test_get_daily_plan_returns_json_serializable_dict(db_session: Session) -> None:
    task_service.create_task(db_session, title="Overdue", due_date=YESTERDAY)

    result = get_daily_plan(db_session, GetDailyPlanArgs())

    assert result["reference_date"] == TODAY.isoformat()
    assert len(result["overdue_tasks"]) == 1
    assert result["overdue_tasks"][0]["title"] == "Overdue"


def test_get_daily_plan_respects_available_minutes(db_session: Session) -> None:
    task_service.create_task(db_session, title="Too long", estimated_minutes=60)
    task_service.create_task(db_session, title="Fits", estimated_minutes=20)

    result = get_daily_plan(db_session, GetDailyPlanArgs(available_minutes=30))

    assert result["suggested_task"] is not None
    assert result["suggested_task"]["title"] == "Fits"


def test_get_daily_plan_args_reject_non_positive_minutes() -> None:
    with pytest.raises(ValidationError):
        GetDailyPlanArgs(available_minutes=0)
