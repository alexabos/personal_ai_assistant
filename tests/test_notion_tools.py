"""Tests for the Notion tools - no real Notion API or LLM involved.

notion_service functions are monkeypatched so these tests isolate argument
translation and result shaping, the tool's own responsibility, from the
service (already covered by test_notion_service.py).
"""

from datetime import date

import pytest
from pydantic import ValidationError

from assistant.services.errors import NotionServiceError
from assistant.services.notion_service import NotionTask
from assistant.tools import notion_tools
from assistant.tools.notion_tools import (
    CreateNotionTaskArgs,
    ListNotionTasksArgs,
    UpdateNotionTaskArgs,
    create_notion_task,
    list_notion_tasks,
    update_notion_task,
)


def test_list_notion_tasks_passes_args_and_shapes_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_list_tasks(**kwargs: object) -> list[NotionTask]:
        captured.update(kwargs)
        return [
            NotionTask(
                id="p1",
                title="Finish report",
                priority="high",
                status="pending",
                deadline=date(2026, 10, 9),
                category="work",
                estimated_minutes=90,
                source="sanofi",
            )
        ]

    monkeypatch.setattr(notion_tools.notion_service, "list_tasks", fake_list_tasks)

    args = ListNotionTasksArgs(
        source="sanofi",
        status="pending",
        deadline_from=date(2026, 10, 1),
        deadline_to=date(2026, 10, 31),
    )
    result = list_notion_tasks(None, args)

    assert captured["source"] == "sanofi"
    assert captured["status"] == "pending"
    assert captured["deadline_from"] == date(2026, 10, 1)
    assert captured["deadline_to"] == date(2026, 10, 31)
    task = result["tasks"][0]
    assert task == {
        "id": "p1",
        "title": "Finish report",
        "priority": "high",
        "status": "pending",
        "deadline": "2026-10-09",
        "category": "work",
        "estimated_minutes": 90,
        "source": "sanofi",
    }


def test_list_notion_tasks_default_source_is_all() -> None:
    args = ListNotionTasksArgs()
    assert args.source == "all"


def test_list_notion_tasks_propagates_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list_tasks(**kwargs: object) -> list[NotionTask]:
        raise NotionServiceError("boom")

    monkeypatch.setattr(notion_tools.notion_service, "list_tasks", fake_list_tasks)

    with pytest.raises(NotionServiceError):
        list_notion_tasks(None, ListNotionTasksArgs())


def test_create_notion_task_passes_args_and_shapes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_create_task(source: str, title: str, **kwargs: object) -> NotionTask:
        captured["source"] = source
        captured["title"] = title
        captured.update(kwargs)
        return NotionTask(id="new-1", title=title, source=source)

    monkeypatch.setattr(notion_tools.notion_service, "create_task", fake_create_task)

    args = CreateNotionTaskArgs(
        source="personal",
        title="Buy milk",
        priority="medium",
        status="pending",
        deadline=date(2026, 10, 10),
        category="errands",
    )
    result = create_notion_task(None, args)

    assert captured["source"] == "personal"
    assert captured["title"] == "Buy milk"
    assert captured["priority"] == "medium"
    assert captured["status"] == "pending"
    assert captured["deadline"] == date(2026, 10, 10)
    assert captured["category"] == "errands"
    assert result["status"] == "created"
    assert result["task"]["id"] == "new-1"


def test_create_notion_task_does_not_report_success_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_task(*args: object, **kwargs: object) -> NotionTask:
        raise NotionServiceError("Unknown source")

    monkeypatch.setattr(notion_tools.notion_service, "create_task", fake_create_task)

    args = CreateNotionTaskArgs(source="nonexistent", title="Task")
    with pytest.raises(NotionServiceError):
        create_notion_task(None, args)


def test_create_notion_task_args_reject_empty_title() -> None:
    with pytest.raises(ValidationError):
        CreateNotionTaskArgs(source="personal", title="   ")


def test_create_notion_task_args_require_source() -> None:
    with pytest.raises(ValidationError):
        CreateNotionTaskArgs(title="Task")  # type: ignore[call-arg]


def test_update_notion_task_passes_args_and_shapes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_update_task(task_id: str, **kwargs: object) -> NotionTask:
        captured["task_id"] = task_id
        captured.update(kwargs)
        return NotionTask(id=task_id, title=kwargs.get("title") or "Task")

    monkeypatch.setattr(notion_tools.notion_service, "update_task", fake_update_task)

    args = UpdateNotionTaskArgs(task_id="p1", status="completed")
    result = update_notion_task(None, args)

    assert captured["task_id"] == "p1"
    assert captured["status"] == "completed"
    assert result["status"] == "updated"
    assert result["task"]["id"] == "p1"


def test_update_notion_task_propagates_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_update_task(*args: object, **kwargs: object) -> NotionTask:
        raise NotionServiceError("API error")

    monkeypatch.setattr(notion_tools.notion_service, "update_task", fake_update_task)

    with pytest.raises(NotionServiceError):
        update_notion_task(None, UpdateNotionTaskArgs(task_id="p1", title="New title"))


def test_update_notion_task_requires_task_id() -> None:
    with pytest.raises(ValidationError):
        UpdateNotionTaskArgs()  # type: ignore[call-arg]
