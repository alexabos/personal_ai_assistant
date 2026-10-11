"""Tests for the Notion service.

The Notion API client is always injected via the `client` parameter, so
these tests never touch real credentials or the network - notion_service's
only credential-reading function (_get_client) is never called here, except
in the dedicated configuration tests below (which monkeypatch get_settings
instead of hitting the real network).
"""

from dataclasses import dataclass
from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest
from notion_client.errors import APIResponseError

from assistant.services import notion_service
from assistant.services.errors import NotionServiceError
from assistant.services.notion_service import (
    _STATUS_VALUE_TO_NOTION,
    create_task,
    list_tasks,
    update_task,
)


@dataclass
class _FakeSettings:
    notion_api_key: str | None = "fake-key"
    notion_database_university: str | None = "db-university"
    notion_database_sanofi: str | None = "db-sanofi"
    notion_database_personal: str | None = "db-personal"


def _api_error(message: str = "boom") -> APIResponseError:
    return APIResponseError(
        code="internal_server_error",
        status=500,
        message=message,
        headers=httpx.Headers({}),
        raw_body_text="{}",
    )


def _notion_page(
    page_id: str,
    title: str,
    *,
    priority: str | None = None,
    status: str | None = None,
    status_type: str = "select",
    deadline: str | None = None,
    category: str | list[str] | None = None,
    category_type: str = "select",
    duration_hours: float | None = None,
) -> dict:
    properties: dict = {"Task": {"type": "title", "title": [{"plain_text": title}]}}
    if duration_hours is not None:
        properties["Duration (h)"] = {"type": "number", "number": duration_hours}
    if priority is not None:
        properties["Priority"] = {"type": "select", "select": {"name": priority}}
    if status is not None:
        properties["Status"] = {"type": status_type, status_type: {"name": status}}
    if deadline is not None:
        properties["Deadline"] = {"type": "date", "date": {"start": deadline}}
    if category is not None:
        if category_type == "multi_select":
            names = category if isinstance(category, list) else [category]
            properties["Category"] = {
                "type": "multi_select",
                "multi_select": [{"name": name} for name in names],
            }
        else:
            properties["Category"] = {"type": "select", "select": {"name": category}}
    return {"id": page_id, "properties": properties}


def _schema(property_types: dict[str, str]) -> dict:
    """A data_sources.retrieve()-shaped response naming each property's type."""
    return {"properties": {name: {"type": prop_type} for name, prop_type in property_types.items()}}


def _mock_client(
    *,
    data_source_ids: dict[str, str] | None = None,
    results_by_data_source: dict[str, dict] | None = None,
    retrieve_error: Exception | None = None,
    query_error_for: dict[str, Exception] | None = None,
) -> MagicMock:
    """A mock Notion client resolving database_id -> data_source_id (via
    databases.retrieve) then querying it (via data_sources.query), mirroring
    the real two-step lookup notion_service performs."""
    client = MagicMock()
    data_source_ids = data_source_ids or {}
    results_by_data_source = results_by_data_source or {}
    query_error_for = query_error_for or {}

    def retrieve_side_effect(database_id: str, **kwargs: object) -> dict:
        if retrieve_error is not None:
            raise retrieve_error
        ds_id = data_source_ids.get(database_id, f"{database_id}-ds")
        return {"data_sources": [{"id": ds_id}]}

    client.databases.retrieve.side_effect = retrieve_side_effect

    def query_side_effect(data_source_id: str, **kwargs: object) -> dict:
        if data_source_id in query_error_for:
            raise query_error_for[data_source_id]
        return results_by_data_source.get(data_source_id, {"results": [], "has_more": False})

    client.data_sources.query.side_effect = query_side_effect
    return client


# --- Configuration ---------------------------------------------------------


def test_get_configured_sources_returns_only_set_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notion_service,
        "get_settings",
        lambda: _FakeSettings(notion_database_sanofi=None, notion_database_personal=None),
    )

    sources = notion_service.get_configured_sources()

    assert sources == {"university": "db-university"}


def test_get_configured_sources_with_multiple_databases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())

    sources = notion_service.get_configured_sources()

    assert sources == {
        "university": "db-university",
        "sanofi": "db-sanofi",
        "personal": "db-personal",
    }


def test_missing_api_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notion_service, "get_settings", lambda: _FakeSettings(notion_api_key=None)
    )

    with pytest.raises(NotionServiceError):
        notion_service._get_client()


# --- Listing ----------------------------------------------------------------


def test_list_tasks_from_one_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-sanofi": "ds-sanofi"},
        results_by_data_source={
            "ds-sanofi": {
                "results": [_notion_page("p1", "Finish report", priority="high")],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="sanofi", client=client)

    assert len(tasks) == 1
    assert tasks[0].title == "Finish report"
    assert tasks[0].source == "sanofi"
    assert tasks[0].priority == "high"


def test_list_tasks_from_all_sources_merges_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={
            "db-university": "ds-uni",
            "db-sanofi": "ds-sanofi",
            "db-personal": "ds-personal",
        },
        results_by_data_source={
            "ds-uni": {"results": [_notion_page("p1", "Prepare lecture")], "has_more": False},
            "ds-sanofi": {"results": [_notion_page("p2", "Finish analysis")], "has_more": False},
            "ds-personal": {"results": [_notion_page("p3", "Buy groceries")], "has_more": False},
        },
    )

    tasks = list_tasks(source="all", client=client)

    assert {task.title for task in tasks} == {"Prepare lecture", "Finish analysis", "Buy groceries"}
    sources = {task.id: task.source for task in tasks}
    assert sources == {"p1": "university", "p2": "sanofi", "p3": "personal"}


def test_list_tasks_sorts_by_deadline_then_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page("no-deadline", "No deadline task"),
                    _notion_page("later", "Later task", deadline="2026-12-01"),
                    _notion_page(
                        "same-day-low", "Same day, low priority",
                        deadline="2026-10-10", priority="low",
                    ),
                    _notion_page(
                        "same-day-high", "Same day, high priority",
                        deadline="2026-10-10", priority="high",
                    ),
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    assert [task.id for task in tasks] == ["same-day-high", "same-day-low", "later", "no-deadline"]


def test_list_tasks_filters_by_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page("p1", "Pending task", status="pending"),
                    _notion_page("p2", "Done task", status="completed"),
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", status="pending", client=client)

    assert [task.id for task in tasks] == ["p1"]


def test_list_tasks_filters_by_deadline_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page("early", "Early", deadline="2026-10-01"),
                    _notion_page("mid", "Mid", deadline="2026-10-10"),
                    _notion_page("late", "Late", deadline="2026-10-20"),
                    _notion_page("none", "No deadline"),
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(
        source="personal",
        deadline_from=date(2026, 10, 5),
        deadline_to=date(2026, 10, 15),
        client=client,
    )

    assert [task.id for task in tasks] == ["mid"]


def test_list_tasks_handles_status_property_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Notion's "Status" can be the classic select type or the newer
    dedicated status type - same {"name": ...} shape, different type key.
    The raw option name ("In progress") is also mapped back to our
    internal vocabulary ("in_progress")."""
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page(
                        "p1", "Status-typed task", status="In progress", status_type="status"
                    )
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    assert tasks[0].status == "in_progress"


def test_list_tasks_maps_notion_option_names_back_to_internal_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page("p1", "Done task", status="Done", status_type="status"),
                    _notion_page(
                        "p2", "Not started task", status="Not started", status_type="status"
                    ),
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    statuses = {task.id: task.status for task in tasks}
    assert statuses == {"p1": "completed", "p2": "pending"}


def test_list_tasks_passes_through_status_option_outside_internal_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Blocked"/"On hold" are real configured options but aren't part of
    our 4-value internal vocabulary - they should surface (lowercased)
    rather than being dropped."""
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [
                    _notion_page(
                        "p1", "Blocked task", status="Blocked", status_type="status"
                    )
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    assert tasks[0].status == "blocked"


def test_list_tasks_handles_missing_properties_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [{"id": "bare", "properties": {}}],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "(untitled)"
    assert task.priority is None
    assert task.status is None
    assert task.deadline is None
    assert task.category is None
    assert task.estimated_minutes is None


def test_list_tasks_reads_duration_as_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-personal": "ds-personal"},
        results_by_data_source={
            "ds-personal": {
                "results": [_notion_page("p1", "Task", duration_hours=1.5)],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="personal", client=client)

    assert tasks[0].estimated_minutes == 90


def test_list_tasks_unknown_source_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())

    with pytest.raises(NotionServiceError):
        list_tasks(source="nonexistent", client=MagicMock())


def test_list_tasks_all_sources_fails_clearly_when_one_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={
            "db-university": "ds-uni",
            "db-sanofi": "ds-sanofi",
            "db-personal": "ds-personal",
        },
        results_by_data_source={
            "ds-uni": {"results": [_notion_page("p1", "Prepare lecture")], "has_more": False},
            "ds-personal": {"results": [_notion_page("p3", "Buy groceries")], "has_more": False},
        },
        query_error_for={"ds-sanofi": _api_error("Sanofi DB unavailable")},
    )

    with pytest.raises(NotionServiceError, match="sanofi"):
        list_tasks(source="all", client=client)


def test_list_tasks_wraps_query_api_error() -> None:
    client = _mock_client(
        data_source_ids={"db-x": "ds-x"},
        query_error_for={"ds-x": _api_error()},
    )

    with pytest.raises(NotionServiceError):
        notion_service._query_source(client, "x", "db-x")


def test_list_tasks_wraps_database_retrieve_error() -> None:
    client = _mock_client(retrieve_error=_api_error("not found"))

    with pytest.raises(NotionServiceError):
        notion_service._resolve_data_source_id(client, "db-x")


# --- Create ------------------------------------------------------------------


def test_create_task_in_correct_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-personal": "ds-personal"})
    client.pages.create.return_value = _notion_page("new-1", "Buy milk")

    task = create_task("personal", "Buy milk", client=client)

    assert task.id == "new-1"
    assert task.source == "personal"
    _, kwargs = client.pages.create.call_args
    assert kwargs["parent"] == {"data_source_id": "ds-personal"}


def test_create_task_maps_priority_and_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-personal": "ds-personal"})
    client.data_sources.retrieve.return_value = _schema({"Priority": "select"})
    client.pages.create.return_value = _notion_page("new-2", "Task")

    create_task(
        "personal",
        "Task",
        priority="high",
        deadline=date(2026, 10, 9),
        client=client,
    )

    _, kwargs = client.pages.create.call_args
    properties = kwargs["properties"]
    assert properties["Priority"] == {"select": {"name": "High"}}
    assert properties["Deadline"] == {"date": {"start": "2026-10-09"}}


@pytest.mark.parametrize("status_value", ["pending", "in_progress", "completed", "cancelled"])
def test_create_task_uses_actual_status_type_from_schema(
    monkeypatch: pytest.MonkeyPatch, status_value: str
) -> None:
    """Reproduces the real bug: a database whose Status property is Notion's
    newer dedicated "status" type, not the classic "select" type. Every
    supported status value must map through the same way - not just one -
    to the database's actual configured option name (e.g. "completed" ->
    "Done"), since Notion rejects an option name that doesn't exist."""
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-personal": "ds-personal"})
    client.data_sources.retrieve.return_value = _schema({"Status": "status"})
    notion_name = _STATUS_VALUE_TO_NOTION[status_value]
    client.pages.create.return_value = _notion_page(
        "new-3", "Task", status=notion_name, status_type="status"
    )

    create_task("personal", "Task", status=status_value, client=client)

    _, kwargs = client.pages.create.call_args
    assert kwargs["properties"]["Status"] == {"status": {"name": notion_name}}


@pytest.mark.parametrize("status_value", ["pending", "in_progress", "completed", "cancelled"])
def test_create_task_uses_select_type_when_schema_says_select(
    monkeypatch: pytest.MonkeyPatch, status_value: str
) -> None:
    """The flip side: a database whose Status is the classic "select" type
    must still get "select", never "status" - per-database, not hardcoded."""
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-sanofi": "ds-sanofi"})
    client.data_sources.retrieve.return_value = _schema({"Status": "select"})
    notion_name = _STATUS_VALUE_TO_NOTION[status_value]
    client.pages.create.return_value = _notion_page("new-4", "Task", status=notion_name)

    create_task("sanofi", "Task", status=status_value, client=client)

    _, kwargs = client.pages.create.call_args
    assert kwargs["properties"]["Status"] == {"select": {"name": notion_name}}


def test_create_task_unknown_source_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())

    with pytest.raises(NotionServiceError):
        create_task("nonexistent", "Task", client=MagicMock())


def test_create_task_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-personal": "ds-personal"})
    client.pages.create.side_effect = _api_error()

    with pytest.raises(NotionServiceError):
        create_task("personal", "Task", client=client)


# --- Update ------------------------------------------------------------------


def _mock_client_for_update(data_source_id: str, property_types: dict[str, str]) -> MagicMock:
    client = MagicMock()
    client.pages.retrieve.return_value = {"parent": {"data_source_id": data_source_id}}
    client.data_sources.retrieve.return_value = _schema(property_types)
    return client


def test_update_task_status() -> None:
    client = _mock_client_for_update("ds-1", {"Status": "select"})
    client.pages.update.return_value = _notion_page("p1", "Task", status="Done")

    task = update_task("p1", status="completed", client=client)

    assert task.status == "completed"
    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Status": {"select": {"name": "Done"}}}


@pytest.mark.parametrize("status_value", ["pending", "in_progress", "completed", "cancelled"])
def test_update_task_uses_actual_status_type_from_schema(status_value: str) -> None:
    """Reproduces the real bug reported live: Notion rejected a "select"-typed
    write because the database's Status property is actually "status"-typed.
    Every supported status value must map through to the database's actual
    configured option name (e.g. "completed" -> "Done"), not just one."""
    client = _mock_client_for_update("ds-1", {"Status": "status"})
    notion_name = _STATUS_VALUE_TO_NOTION[status_value]
    client.pages.update.return_value = _notion_page(
        "p1", "Task", status=notion_name, status_type="status"
    )

    task = update_task("p1", status=status_value, client=client)

    assert task.status == status_value
    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Status": {"status": {"name": notion_name}}}


@pytest.mark.parametrize("status_value", ["pending", "in_progress", "completed", "cancelled"])
def test_update_task_uses_select_type_when_schema_says_select(status_value: str) -> None:
    """The flip side: a database whose Status is the classic "select" type
    must still get "select", never "status" - per-database, not hardcoded."""
    client = _mock_client_for_update("ds-1", {"Status": "select"})
    notion_name = _STATUS_VALUE_TO_NOTION[status_value]
    client.pages.update.return_value = _notion_page("p1", "Task", status=notion_name)

    task = update_task("p1", status=status_value, client=client)

    assert task.status == status_value
    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Status": {"select": {"name": notion_name}}}


def test_update_task_status_passes_through_option_outside_internal_vocabulary() -> None:
    """"Blocked"/"On hold" aren't in our 4-value internal vocabulary but are
    real configured options - a caller who already knows the Notion name
    can use it directly rather than being rejected."""
    client = _mock_client_for_update("ds-1", {"Status": "status"})
    client.pages.update.return_value = _notion_page(
        "p1", "Task", status="Blocked", status_type="status"
    )

    task = update_task("p1", status="Blocked", client=client)

    assert task.status == "blocked"
    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Status": {"status": {"name": "Blocked"}}}


def test_update_task_priority() -> None:
    client = _mock_client_for_update("ds-1", {"Priority": "select"})
    client.pages.update.return_value = _notion_page("p1", "Task", priority="Low")

    update_task("p1", priority="low", client=client)

    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Priority": {"select": {"name": "Low"}}}


def test_update_task_deadline() -> None:
    client = MagicMock()
    client.pages.update.return_value = _notion_page("p1", "Task", deadline="2026-11-01")

    task = update_task("p1", deadline=date(2026, 11, 1), client=client)

    assert task.deadline == date(2026, 11, 1)
    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"] == {"Deadline": {"date": {"start": "2026-11-01"}}}
    # Deadline never needs schema lookup - no select-like property involved.
    client.pages.retrieve.assert_not_called()


def test_update_task_title_and_category() -> None:
    client = _mock_client_for_update("ds-1", {"Category": "select"})
    client.pages.update.return_value = _notion_page("p1", "New title", category="Work")

    update_task("p1", title="New title", category="Work", client=client)

    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"]["Task"] == {"title": [{"text": {"content": "New title"}}]}
    assert kwargs["properties"]["Category"] == {"select": {"name": "Work"}}


def test_update_task_writes_multi_select_category_when_schema_says_multi_select() -> None:
    """Some real databases use multi_select for Category instead of select -
    the write must wrap the single given value as a one-element list."""
    client = _mock_client_for_update("ds-1", {"Category": "multi_select"})
    client.pages.update.return_value = _notion_page(
        "p1", "Task", category="Work", category_type="multi_select"
    )

    update_task("p1", category="Work", client=client)

    _, kwargs = client.pages.update.call_args
    assert kwargs["properties"]["Category"] == {"multi_select": [{"name": "Work"}]}


def test_create_task_writes_multi_select_category_when_schema_says_multi_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(data_source_ids={"db-sanofi": "ds-sanofi"})
    client.data_sources.retrieve.return_value = _schema({"Category": "multi_select"})
    client.pages.create.return_value = _notion_page(
        "new-5", "Task", category="Deployment", category_type="multi_select"
    )

    create_task("sanofi", "Task", category="Deployment", client=client)

    _, kwargs = client.pages.create.call_args
    assert kwargs["properties"]["Category"] == {"multi_select": [{"name": "Deployment"}]}


def test_list_tasks_reads_multi_select_category(monkeypatch: pytest.MonkeyPatch) -> None:
    """A multi_select Category with several values is joined into one
    comma-separated string, rather than being silently dropped as None."""
    monkeypatch.setattr(notion_service, "get_settings", lambda: _FakeSettings())
    client = _mock_client(
        data_source_ids={"db-sanofi": "ds-sanofi"},
        results_by_data_source={
            "ds-sanofi": {
                "results": [
                    _notion_page(
                        "p1",
                        "Task",
                        category=["Trainings", "Deployment"],
                        category_type="multi_select",
                    )
                ],
                "has_more": False,
            }
        },
    )

    tasks = list_tasks(source="sanofi", client=client)

    assert tasks[0].category == "trainings, deployment"


def test_update_task_resolves_schema_once_for_multiple_fields() -> None:
    """priority + status + category together should only look up the page's
    data source and schema once each, not once per field."""
    client = _mock_client_for_update("ds-1", {"Priority": "select", "Status": "status"})
    client.pages.update.return_value = _notion_page("p1", "Task")

    update_task("p1", priority="high", status="completed", client=client)

    assert client.pages.retrieve.call_count == 1


def test_update_task_source_is_none() -> None:
    """update_task doesn't require/know the source - genuinely unknown, not guessed."""
    client = MagicMock()
    client.pages.update.return_value = _notion_page("p1", "Task")

    task = update_task("p1", title="Task", client=client)

    assert task.source is None


def test_update_task_wraps_api_error() -> None:
    client = MagicMock()
    client.pages.update.side_effect = _api_error()

    with pytest.raises(NotionServiceError):
        update_task("p1", title="Task", client=client)


def test_get_property_type_defaults_to_select_when_missing_from_schema() -> None:
    client = MagicMock()
    client.data_sources.retrieve.return_value = _schema({})

    prop_type = notion_service._get_property_type(client, "ds-1", "Category")

    assert prop_type == "select"
