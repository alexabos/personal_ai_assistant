"""HTTP routes for task management."""

from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from assistant.db.database import get_db
from assistant.db.models import TaskPriority, TaskStatus
from assistant.schemas.tasks import TaskCreate, TaskRead, TaskUpdate
from assistant.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> TaskRead:
    """Create a new task."""
    task = task_service.create_task(
        db,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_date=payload.due_date,
        estimated_minutes=payload.estimated_minutes,
        category=payload.category,
    )
    return TaskRead.model_validate(task)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    db: Session = Depends(get_db),
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    category: str | None = None,
    due_date: date | None = None,
    include_completed: bool = False,
) -> list[TaskRead]:
    """List tasks. Completed tasks are excluded unless include_completed=true."""
    tasks = task_service.list_tasks(
        db,
        status=status,
        priority=priority,
        category=category,
        due_date=due_date,
        include_completed=include_completed,
    )
    return [TaskRead.model_validate(task) for task in tasks]


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskRead:
    """Retrieve a single task by id."""
    task = task_service.get_task(db, task_id)
    return TaskRead.model_validate(task)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> TaskRead:
    """Partially update a task."""
    task = task_service.update_task(
        db,
        task_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        due_date=payload.due_date,
        estimated_minutes=payload.estimated_minutes,
        category=payload.category,
    )
    return TaskRead.model_validate(task)


@router.post("/{task_id}/complete", response_model=TaskRead)
def complete_task(task_id: int, db: Session = Depends(get_db)) -> TaskRead:
    """Mark a task as completed."""
    task = task_service.complete_task(db, task_id)
    return TaskRead.model_validate(task)


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(task_id: int, db: Session = Depends(get_db)) -> TaskRead:
    """Mark a task as cancelled."""
    task = task_service.cancel_task(db, task_id)
    return TaskRead.model_validate(task)
