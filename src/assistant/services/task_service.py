"""Business logic for task management.

Framework-agnostic by design: functions here take a SQLAlchemy Session and
plain arguments, and return ORM objects or raise service-level exceptions.
This keeps them directly callable as future LLM tools without any FastAPI
dependency.
"""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.db.models import Task, TaskPriority, TaskStatus
from assistant.services.errors import InvalidStateTransitionError, NotFoundError


def _utcnow() -> datetime:
    """Return a naive UTC timestamp, consistent with SQLite storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def create_task(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    priority: TaskPriority = TaskPriority.MEDIUM,
    due_date: date | None = None,
    estimated_minutes: int | None = None,
    category: str | None = None,
) -> Task:
    """Create and persist a new task."""
    task = Task(
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        estimated_minutes=estimated_minutes,
        category=category,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task:
    """Return a task by id, or raise NotFoundError."""
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"Task {task_id} not found")
    return task


def list_tasks(
    db: Session,
    *,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    category: str | None = None,
    due_date: date | None = None,
    include_completed: bool = False,
) -> list[Task]:
    """List tasks, optionally filtered.

    Completed tasks are excluded by default unless a status filter is given
    or include_completed=True is passed explicitly.
    """
    stmt = select(Task)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    elif not include_completed:
        stmt = stmt.where(Task.status != TaskStatus.COMPLETED)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if category is not None:
        stmt = stmt.where(Task.category == category)
    if due_date is not None:
        stmt = stmt.where(Task.due_date == due_date)
    stmt = stmt.order_by(Task.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def _apply_status(task: Task, new_status: TaskStatus) -> None:
    """Set a task's status while keeping completed_at consistent."""
    task.status = new_status
    if new_status == TaskStatus.COMPLETED:
        if task.completed_at is None:
            task.completed_at = _utcnow()
    else:
        task.completed_at = None


def update_task(
    db: Session,
    task_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    due_date: date | None = None,
    estimated_minutes: int | None = None,
    category: str | None = None,
) -> Task:
    """Partially update a task's fields."""
    task = get_task(db, task_id)

    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if priority is not None:
        task.priority = priority
    if due_date is not None:
        task.due_date = due_date
    if estimated_minutes is not None:
        task.estimated_minutes = estimated_minutes
    if category is not None:
        task.category = category
    if status is not None:
        _apply_status(task, status)

    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task_id: int) -> Task:
    """Mark a task as completed.

    Idempotent if already completed. Rejects cancelled tasks.
    """
    task = get_task(db, task_id)
    if task.status == TaskStatus.CANCELLED:
        raise InvalidStateTransitionError(f"Task {task_id} is cancelled and cannot be completed")
    if task.status != TaskStatus.COMPLETED:
        _apply_status(task, TaskStatus.COMPLETED)
        db.commit()
        db.refresh(task)
    return task


def cancel_task(db: Session, task_id: int) -> Task:
    """Mark a task as cancelled.

    Idempotent if already cancelled. Rejects completed tasks.
    """
    task = get_task(db, task_id)
    if task.status == TaskStatus.COMPLETED:
        raise InvalidStateTransitionError(f"Task {task_id} is completed and cannot be cancelled")
    if task.status != TaskStatus.CANCELLED:
        _apply_status(task, TaskStatus.CANCELLED)
        db.commit()
        db.refresh(task)
    return task
