"""Notion integration: querying and managing tasks across configured databases.

Framework-agnostic by design: see task_service.py for the rationale.
Independent from the SQLite task service by design - Notion is an external
task source here, not synchronized with or duplicated into SQLite.

Notion's API (2025-09-03+) organizes pages under "data sources" rather than
database IDs directly - a personal database has exactly one data source,
resolved transparently by _resolve_data_source_id. Callers only ever deal
with logical source names (e.g. "university") configured via Settings,
never raw database or data source IDs - the LLM cannot supply an arbitrary
database ID.

Unlike calendar_service.list_events (which skips a calendar that fails),
list_tasks(source="all") raises on the first source that fails to query,
naming it - partial results are never silently returned as if complete.
"""

from datetime import date, datetime
from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError
from pydantic import BaseModel

from assistant.config.settings import get_settings
from assistant.services.errors import NotionServiceError

_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

# Notion property names as configured in the user's databases. Centralized
# here so a naming mismatch found during live testing is a one-line fix,
# not a redesign.
TITLE_PROPERTY = "Task"
PRIORITY_PROPERTY = "Priority"
STATUS_PROPERTY = "Status"
DEADLINE_PROPERTY = "Deadline"
CATEGORY_PROPERTY = "Category"
DURATION_PROPERTY = "Duration (h)"

# Maps our internal status vocabulary to the Status option names actually
# configured in the user's databases (confirmed identical across all three
# via live inspection). "Blocked" and "On hold" aren't part of our internal
# vocabulary but are real configured options - they pass through unchanged
# (see _status_value_to_notion/_status_value_from_notion) rather than being
# rejected, so they remain directly usable.
_STATUS_VALUE_TO_NOTION: dict[str, str] = {
    "pending": "Not started",
    "in_progress": "In progress",
    "completed": "Done",
    "cancelled": "Cancelled",
}
_NOTION_STATUS_TO_VALUE: dict[str, str] = {
    name.lower(): value for value, name in _STATUS_VALUE_TO_NOTION.items()
}


class NotionTask(BaseModel):
    """Internal, normalized representation of a Notion task page."""

    id: str
    title: str
    priority: str | None = None
    status: str | None = None
    deadline: date | None = None
    category: str | None = None
    estimated_minutes: int | None = None
    source: str | None = None


def get_configured_sources() -> dict[str, str]:
    """Return {source_name: database_id} for every configured Notion source."""
    settings = get_settings()
    sources = {
        "university": settings.notion_database_university,
        "sanofi": settings.notion_database_sanofi,
        "personal": settings.notion_database_personal,
    }
    return {name: database_id for name, database_id in sources.items() if database_id}


def _get_client() -> Client:
    """Build an authenticated Notion client. Non-interactive: a bare bearer
    token from configuration, no OAuth flow."""
    settings = get_settings()
    if not settings.notion_api_key:
        raise NotionServiceError(
            "Notion is not configured. Set NOTION_API_KEY (and at least one "
            "NOTION_DATABASE_* source) in your .env file."
        )
    return Client(auth=settings.notion_api_key)


def _resolve_source(source: str) -> str:
    """Resolve a logical source name to its configured database ID.

    Raises NotionServiceError for an unknown source - the LLM can only ever
    select from configured logical names, never supply a raw database ID.
    """
    sources = get_configured_sources()
    database_id = sources.get(source)
    if database_id is None:
        available = ", ".join(sorted(sources)) or "(none configured)"
        raise NotionServiceError(f"Unknown source '{source}'. Configured sources: {available}.")
    return database_id


def _resolve_data_source_id(client: Any, database_id: str) -> str:
    """Resolve a database ID to its data source ID (Notion API 2025-09-03+).

    A personal database has exactly one data source; the first is used.
    Not cached: kept simple, and the extra call is negligible for this
    usage pattern.
    """
    try:
        database = client.databases.retrieve(database_id=database_id)
    except APIResponseError as exc:
        raise NotionServiceError(f"Failed to look up database '{database_id}': {exc}") from exc
    data_sources = database.get("data_sources") or []
    if not data_sources:
        raise NotionServiceError(f"Database '{database_id}' has no data sources.")
    return data_sources[0]["id"]


def _get_property_type(
    client: Any, data_source_id: str, property_name: str, default: str = "select"
) -> str:
    """Look up a property's actual type on a data source's schema.

    Notion rejects a write using the wrong select-like type (e.g. sending
    "select" for a property actually configured as the newer "status"
    type) - this resolves the real type first so writes always match.
    Falls back to `default` if the property isn't found in the schema.
    """
    try:
        schema = client.data_sources.retrieve(data_source_id=data_source_id)
    except APIResponseError as exc:
        raise NotionServiceError(
            f"Failed to look up schema for data source '{data_source_id}': {exc}"
        ) from exc
    prop = schema.get("properties", {}).get(property_name)
    if prop is None:
        return default
    return prop.get("type", default)


def _select_like_property(prop_type: str, name: str) -> dict[str, Any]:
    """Build a select-, status-, or multi_select-typed property value,
    matching the database's actual property type - Notion rejects the
    wrong one. multi_select wraps the single given name as a one-element
    list (the tool only accepts one category value at a time)."""
    if prop_type == "multi_select":
        return {"multi_select": [{"name": name}]}
    return {prop_type: {"name": name}}


def _status_value_to_notion(value: str) -> str:
    """Map our internal status vocabulary to the database's actual
    configured option name. A value outside that vocabulary (e.g. already
    "Blocked" or "On hold") passes through unchanged, so a caller who
    already knows the real Notion option name can still use it directly."""
    return _STATUS_VALUE_TO_NOTION.get(value.strip().lower(), value)


def _status_value_from_notion(name: str) -> str:
    """Map a Notion-native status option name back to our internal
    vocabulary. Options outside that vocabulary (e.g. "Blocked", "On hold")
    pass through unchanged (lowercased) rather than being dropped."""
    lowered = name.lower()
    return _NOTION_STATUS_TO_VALUE.get(lowered, lowered)


def _priority_value_to_notion(value: str) -> str:
    """Notion's Priority options are Title-Case ("High"/"Medium"/"Low");
    our internal vocabulary is lowercase - capitalize to match."""
    return value.strip().capitalize()


def _resolve_data_source_id_for_page(client: Any, task_id: str) -> str:
    """Resolve the data source a page belongs to, by retrieving the page
    itself and reading its parent. Lets update_task look up schema without
    requiring the caller to know/pass the source."""
    try:
        page = client.pages.retrieve(page_id=task_id)
    except APIResponseError as exc:
        raise NotionServiceError(f"Failed to look up task '{task_id}': {exc}") from exc
    data_source_id = (page.get("parent") or {}).get("data_source_id")
    if not data_source_id:
        raise NotionServiceError(f"Could not determine the data source for task '{task_id}'.")
    return data_source_id


def _extract_select(prop: dict[str, Any] | None) -> str | None:
    """Read a select-like property's value: Notion's "select" and "status"
    types (a single {"name": ...} object), or "multi_select" (a list of
    them, joined into one comma-separated string) - real databases vary in
    which of these an otherwise-identical-looking property actually uses."""
    if prop is None:
        return None
    prop_type = prop.get("type")
    if prop_type == "multi_select":
        items = prop.get("multi_select") or []
        names = [item.get("name") for item in items if isinstance(item, dict)]
        lowered = [name.lower() for name in names if isinstance(name, str)]
        return ", ".join(lowered) if lowered else None
    value = prop.get(prop_type) if prop_type else None
    if isinstance(value, dict):
        name = value.get("name")
        return name.lower() if isinstance(name, str) else None
    return None


def _extract_title(prop: dict[str, Any] | None) -> str:
    if prop is None:
        return "(untitled)"
    fragments = prop.get("title") or []
    text = "".join(fragment.get("plain_text", "") for fragment in fragments)
    return text or "(untitled)"


def _extract_date(prop: dict[str, Any] | None) -> date | None:
    if prop is None:
        return None
    date_value = prop.get("date")
    if not date_value or not date_value.get("start"):
        return None
    return datetime.fromisoformat(date_value["start"]).date()


def _extract_duration_minutes(prop: dict[str, Any] | None) -> int | None:
    """Read the Duration (h) number property and convert hours to minutes.
    Read-only for now: not yet settable via create_task/update_task."""
    if prop is None:
        return None
    hours = prop.get("number")
    if not isinstance(hours, int | float):
        return None
    return round(hours * 60)


def _page_to_task(page: dict[str, Any], source: str | None) -> NotionTask:
    properties = page.get("properties", {})
    raw_status = _extract_select(properties.get(STATUS_PROPERTY))
    return NotionTask(
        id=page["id"],
        title=_extract_title(properties.get(TITLE_PROPERTY)),
        priority=_extract_select(properties.get(PRIORITY_PROPERTY)),
        status=_status_value_from_notion(raw_status) if raw_status is not None else None,
        deadline=_extract_date(properties.get(DEADLINE_PROPERTY)),
        category=_extract_select(properties.get(CATEGORY_PROPERTY)),
        estimated_minutes=_extract_duration_minutes(properties.get(DURATION_PROPERTY)),
        source=source,
    )


def _query_source(client: Any, source: str, database_id: str) -> list[NotionTask]:
    data_source_id = _resolve_data_source_id(client, database_id)
    tasks: list[NotionTask] = []
    start_cursor: str | None = None
    try:
        while True:
            kwargs: dict[str, Any] = {}
            if start_cursor is not None:
                kwargs["start_cursor"] = start_cursor
            response = client.data_sources.query(data_source_id=data_source_id, **kwargs)
            tasks.extend(_page_to_task(page, source) for page in response.get("results", []))
            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")
    except APIResponseError as exc:
        raise NotionServiceError(f"Failed to query Notion source '{source}': {exc}") from exc
    return tasks


def _sort_key(task: NotionTask) -> tuple[bool, date, int]:
    return (
        task.deadline is None,
        task.deadline or date.max,
        _PRIORITY_RANK.get(task.priority or "", len(_PRIORITY_RANK)),
    )


def list_tasks(
    *,
    source: str = "all",
    status: str | None = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    client: Any | None = None,
) -> list[NotionTask]:
    """List tasks from one configured source, or every configured source
    ("all", the default).

    Raises NotionServiceError (naming the failing source) if any source
    cannot be queried when source="all" - partial results are never
    silently returned as if complete.
    """
    resource = client if client is not None else _get_client()

    if source == "all":
        sources_to_query = get_configured_sources()
    else:
        sources_to_query = {source: _resolve_source(source)}

    tasks: list[NotionTask] = []
    for name, database_id in sources_to_query.items():
        tasks.extend(_query_source(resource, name, database_id))

    if status is not None:
        lowered_status = status.strip().lower()
        tasks = [task for task in tasks if task.status == lowered_status]
    if deadline_from is not None:
        tasks = [t for t in tasks if t.deadline is not None and t.deadline >= deadline_from]
    if deadline_to is not None:
        tasks = [t for t in tasks if t.deadline is not None and t.deadline <= deadline_to]

    tasks.sort(key=_sort_key)
    return tasks


def create_task(
    source: str,
    title: str,
    *,
    priority: str | None = None,
    status: str | None = None,
    deadline: date | None = None,
    category: str | None = None,
    client: Any | None = None,
) -> NotionTask:
    """Create a task in the given configured source.

    Raises NotionServiceError for an unknown source or if the Notion API
    call fails - never returns a fabricated task.
    """
    database_id = _resolve_source(source)
    resource = client if client is not None else _get_client()
    data_source_id = _resolve_data_source_id(resource, database_id)

    properties: dict[str, Any] = {
        TITLE_PROPERTY: {"title": [{"text": {"content": title}}]},
    }
    if priority is not None:
        prop_type = _get_property_type(resource, data_source_id, PRIORITY_PROPERTY)
        properties[PRIORITY_PROPERTY] = _select_like_property(
            prop_type, _priority_value_to_notion(priority)
        )
    if status is not None:
        prop_type = _get_property_type(resource, data_source_id, STATUS_PROPERTY)
        properties[STATUS_PROPERTY] = _select_like_property(
            prop_type, _status_value_to_notion(status)
        )
    if deadline is not None:
        properties[DEADLINE_PROPERTY] = {"date": {"start": deadline.isoformat()}}
    if category is not None:
        prop_type = _get_property_type(resource, data_source_id, CATEGORY_PROPERTY)
        properties[CATEGORY_PROPERTY] = _select_like_property(prop_type, category)

    try:
        created = resource.pages.create(
            parent={"data_source_id": data_source_id}, properties=properties
        )
    except APIResponseError as exc:
        raise NotionServiceError(f"Failed to create task in '{source}': {exc}") from exc

    # The SDK types every call as sync-or-async (SyncAsync[Any]); the sync
    # Client used here always returns the dict directly, never an awaitable.
    return _page_to_task(created, source)  # type: ignore[arg-type]


def update_task(
    task_id: str,
    *,
    title: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    deadline: date | None = None,
    category: str | None = None,
    client: Any | None = None,
) -> NotionTask:
    """Update an existing task's properties by its Notion page ID.

    The source does not need to be specified - Notion page IDs are globally
    addressable, so the returned task's `source` is None (genuinely unknown
    here, not guessed). Raises NotionServiceError if the Notion API call
    fails.
    """
    resource = client if client is not None else _get_client()

    properties: dict[str, Any] = {}
    if title is not None:
        properties[TITLE_PROPERTY] = {"title": [{"text": {"content": title}}]}

    _resolved_data_source_id: str | None = None

    def _data_source_id_for_this_page() -> str:
        # Resolved lazily and at most once, even if several select-like
        # properties are updated in the same call.
        nonlocal _resolved_data_source_id
        if _resolved_data_source_id is None:
            _resolved_data_source_id = _resolve_data_source_id_for_page(resource, task_id)
        return _resolved_data_source_id

    if priority is not None:
        prop_type = _get_property_type(
            resource, _data_source_id_for_this_page(), PRIORITY_PROPERTY
        )
        properties[PRIORITY_PROPERTY] = _select_like_property(
            prop_type, _priority_value_to_notion(priority)
        )
    if status is not None:
        prop_type = _get_property_type(resource, _data_source_id_for_this_page(), STATUS_PROPERTY)
        properties[STATUS_PROPERTY] = _select_like_property(
            prop_type, _status_value_to_notion(status)
        )
    if deadline is not None:
        properties[DEADLINE_PROPERTY] = {"date": {"start": deadline.isoformat()}}
    if category is not None:
        prop_type = _get_property_type(
            resource, _data_source_id_for_this_page(), CATEGORY_PROPERTY
        )
        properties[CATEGORY_PROPERTY] = _select_like_property(prop_type, category)

    try:
        updated = resource.pages.update(page_id=task_id, properties=properties)
    except APIResponseError as exc:
        raise NotionServiceError(f"Failed to update task '{task_id}': {exc}") from exc

    return _page_to_task(updated, source=None)  # type: ignore[arg-type]
