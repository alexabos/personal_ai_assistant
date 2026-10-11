"""LLM-callable tools wrapping the Notion service.

Each tool here is a thin translator, same pattern as calendar_tools.py: it
declares a small Pydantic args model (validation for the LLM's raw,
untrusted arguments) and a handler that calls straight into notion_service -
no Notion API logic lives here.

The `db` parameter on each handler is required by the shared Tool.handler
signature but unused: Notion tools talk to Notion, not the local database.

Source names are never hardcoded here: the list of configured sources is
read from notion_service.get_configured_sources() once at import time and
interpolated into the tool descriptions, so the LLM only ever sees sources
that actually exist in configuration.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from assistant.services import notion_service
from assistant.tools.registry import Tool

_CONFIGURED_SOURCES = ", ".join(sorted(notion_service.get_configured_sources())) or (
    "(none configured)"
)


class ListNotionTasksArgs(BaseModel):
    """Arguments for the list_notion_tasks tool."""

    source: str = Field(
        default="all",
        description=(
            f"Which Notion task source to query. One of: {_CONFIGURED_SOURCES}, "
            "or 'all' (default) to query every configured source at once."
        ),
    )
    status: str | None = Field(
        default=None,
        description=(
            "Optional status filter, e.g. 'pending', 'in_progress', "
            "'completed', 'cancelled'."
        ),
    )
    deadline_from: date | None = Field(
        default=None, description="Optional: only tasks with a deadline on or after this date."
    )
    deadline_to: date | None = Field(
        default=None, description="Optional: only tasks with a deadline on or before this date."
    )


class CreateNotionTaskArgs(BaseModel):
    """Arguments for the create_notion_task tool."""

    source: str = Field(
        description=(
            f"Which Notion source to create the task in. Must be one of: "
            f"{_CONFIGURED_SOURCES} - never a raw database ID."
        )
    )
    title: str = Field(min_length=1, description="Task title.")
    priority: str | None = Field(default=None, description="Optional: 'high', 'medium', 'low'.")
    status: str | None = Field(
        default=None,
        description="Optional: 'pending', 'in_progress', 'completed', 'cancelled'.",
    )
    deadline: date | None = Field(default=None, description="Optional deadline date.")
    category: str | None = Field(default=None, description="Optional category/tag.")

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be empty")
        return stripped


class UpdateNotionTaskArgs(BaseModel):
    """Arguments for the update_notion_task tool."""

    task_id: str = Field(description="The Notion page ID of the task to update.")
    title: str | None = Field(default=None, description="New title, if changing it.")
    priority: str | None = Field(default=None, description="New priority, if changing it.")
    status: str | None = Field(default=None, description="New status, if changing it.")
    deadline: date | None = Field(default=None, description="New deadline, if changing it.")
    category: str | None = Field(default=None, description="New category/tag, if changing it.")


def list_notion_tasks(db: Session, args: BaseModel) -> dict[str, Any]:
    """Return matching Notion tasks as concise, JSON-serializable data."""
    assert isinstance(args, ListNotionTasksArgs)
    tasks = notion_service.list_tasks(
        source=args.source,
        status=args.status,
        deadline_from=args.deadline_from,
        deadline_to=args.deadline_to,
    )
    return {"tasks": [task.model_dump(mode="json") for task in tasks]}


def create_notion_task(db: Session, args: BaseModel) -> dict[str, Any]:
    """Create a Notion task and return a confirmation as JSON-serializable data."""
    assert isinstance(args, CreateNotionTaskArgs)
    task = notion_service.create_task(
        args.source,
        args.title,
        priority=args.priority,
        status=args.status,
        deadline=args.deadline,
        category=args.category,
    )
    return {"status": "created", "task": task.model_dump(mode="json")}


def update_notion_task(db: Session, args: BaseModel) -> dict[str, Any]:
    """Update a Notion task and return a confirmation as JSON-serializable data."""
    assert isinstance(args, UpdateNotionTaskArgs)
    task = notion_service.update_task(
        args.task_id,
        title=args.title,
        priority=args.priority,
        status=args.status,
        deadline=args.deadline,
        category=args.category,
    )
    return {"status": "updated", "task": task.model_dump(mode="json")}


LIST_NOTION_TASKS_TOOL = Tool(
    name="list_notion_tasks",
    description=(
        "List the user's external tasks from Notion. Notion holds several "
        f"separate task sources: {_CONFIGURED_SOURCES}. Call this whenever the "
        "user asks about tasks, deadlines, or to-dos from one of these "
        "sources, or across all of them. Pass source='all' (default) unless "
        "the user clearly asks about one specific source - e.g. 'my Sanofi "
        "tasks' means source='sanofi', not 'all'."
    ),
    args_model=ListNotionTasksArgs,
    handler=list_notion_tasks,
)

CREATE_NOTION_TASK_TOOL = Tool(
    name="create_notion_task",
    description=(
        "Create a new task in one of the user's Notion task sources "
        f"({_CONFIGURED_SOURCES}). Call this when the user asks to add a task "
        "or to-do to one of these sources. You must pick exactly one source - "
        "ask the user which one if it isn't clear from context."
    ),
    args_model=CreateNotionTaskArgs,
    handler=create_notion_task,
)

UPDATE_NOTION_TASK_TOOL = Tool(
    name="update_notion_task",
    description=(
        "Update an existing Notion task's properties (title, priority, "
        "status, deadline, or category) by its page ID - typically after "
        "listing tasks and identifying which one the user means. Only the "
        "fields you pass are changed; omit the rest."
    ),
    args_model=UpdateNotionTaskArgs,
    handler=update_notion_task,
)

NOTION_TOOLS: list[Tool] = [
    LIST_NOTION_TASKS_TOOL,
    CREATE_NOTION_TASK_TOOL,
    UPDATE_NOTION_TASK_TOOL,
]
