# Personal AI Assistant

## Project

A personal AI assistant backend, designed to eventually run on a Raspberry Pi
as a voice-first assistant for daily life management.

## Vision

The finished assistant will be a **voice-first personal assistant**, interacted
with primarily in **Catalan**, capable of managing:

- daily and weekly tasks
- weekly goals
- calendar events
- learning progress
- time-aware task suggestions
- voice interaction (speech-to-text / text-to-speech / wake word)

All code, technical naming, and documentation are kept in **English**, regardless
of the language used in the user-facing conversation.

## Architecture

The system is organized into modular components:

| Component | Purpose | Status |
|---|---|---|
| `api/` | FastAPI HTTP layer (routes, request/response handling) | Implemented (health, tasks, weekly goals) |
| `db/` | Database engine, session management, ORM models | Implemented (Task, WeeklyGoal) |
| `schemas/` | Pydantic request/response models for the API | Implemented (tasks, weekly goals) |
| `services/` | Business logic, independent of FastAPI | Implemented (task and weekly goal services) |
| `config/` | Application settings via environment variables | Implemented |
| `agent/` | LLM-driven agent orchestration (planning, reasoning) | Planned |
| `tools/` | Agent-callable tools (tasks, calendar, goals, learning) | Planned |
| Voice interface | Wake word, STT, TTS | Planned |
| Raspberry Pi client | Hardware integration for always-on voice assistant | Planned |

Responsibilities are kept separated on purpose:

- **ORM models** (`db/models.py`) define persistence only.
- **Pydantic schemas** (`schemas/`) define API input/output validation and serialization.
- **Services** (`services/`) contain all business logic (state transitions, filtering,
  normalization). They take a SQLAlchemy `Session` and plain arguments, return ORM
  objects, and raise plain Python exceptions (`services/errors.py`) — no FastAPI
  dependency. This keeps them directly reusable as LLM tool-calling targets in a
  later phase.
- **API routes** (`api/routes/`) handle HTTP concerns only: request/response
  shaping and translating service exceptions into HTTP status codes (via global
  exception handlers registered in `main.py`).

## Current status

**Phase 2** is complete, building on the Phase 1 backend foundation. The API now
supports full CRUD-style management of **tasks** and **weekly goals**, backed by
SQLite via SQLAlchemy. No LLM, agent, tools, voice, or external integrations
(Notion, Google Calendar, etc.) are implemented yet.

Database tables are created automatically on application startup
(`Base.metadata.create_all`) — no migration tool is used at this stage.

## API reference

### Tasks

| Method | Path | Description |
|---|---|---|
| `POST` | `/tasks` | Create a task |
| `GET` | `/tasks` | List tasks (filters: `status`, `priority`, `category`, `due_date`, `include_completed`) |
| `GET` | `/tasks/{task_id}` | Retrieve a task |
| `PATCH` | `/tasks/{task_id}` | Update a task's fields |
| `POST` | `/tasks/{task_id}/complete` | Mark a task as completed |
| `POST` | `/tasks/{task_id}/cancel` | Mark a task as cancelled |

Create a task:

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Study agentic AI",
    "description": "Complete the next course lesson",
    "priority": "high",
    "estimated_minutes": 45,
    "category": "learning",
    "due_date": "2026-09-20"
  }'
```

**Task fields**: `id`, `title`, `description`, `status`
(`pending` / `in_progress` / `completed` / `cancelled`), `priority`
(`low` / `medium` / `high`), `due_date`, `estimated_minutes`, `category`,
`created_at`, `completed_at`.

**Notes:**

- `GET /tasks` excludes `completed` tasks by default. Pass
  `?include_completed=true` to include them. An explicit `status` filter
  always overrides this default.
- Deletion is intentionally not exposed. Use `POST /tasks/{id}/cancel` instead,
  which preserves history.
- `complete`/`cancel` are idempotent when re-applied to a task already in that
  state (`200`, no change). Completing a cancelled task, or cancelling a
  completed task, returns `409 Conflict`.
- `completed_at` is managed automatically: it is set when a task becomes
  `completed` and cleared if the status changes away from `completed`
  (including via `PATCH`).

### Weekly goals

| Method | Path | Description |
|---|---|---|
| `POST` | `/weekly-goals` | Create a weekly goal |
| `GET` | `/weekly-goals` | List weekly goals (filters: `week_start`, `status`) |
| `GET` | `/weekly-goals/{goal_id}` | Retrieve a weekly goal |
| `PATCH` | `/weekly-goals/{goal_id}` | Update a weekly goal's fields |
| `POST` | `/weekly-goals/{goal_id}/complete` | Mark a weekly goal as completed |
| `POST` | `/weekly-goals/{goal_id}/cancel` | Mark a weekly goal as cancelled |

Create a weekly goal:

```bash
curl -X POST http://127.0.0.1:8000/weekly-goals \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Improve French speaking",
    "description": "Complete five speaking sessions",
    "week_start": "2026-09-14",
    "target_minutes": 150
  }'
```

**Weekly goal fields**: `id`, `title`, `description`, `week_start`,
`target_minutes`, `completed_minutes`, `status`
(`active` / `completed` / `cancelled`), `created_at`.

**Notes:**

- `week_start` is always **normalized to the Monday** of its calendar week,
  both on create/update and when used as a filter — the value sent does not
  need to already be a Monday.
- `complete`/`cancel` follow the same idempotency and conflict rules as tasks.

### Validation summary

- Task and goal titles cannot be empty or whitespace-only.
- `estimated_minutes` and `target_minutes` must be positive when provided.
- `completed_minutes` must be non-negative.
- `status` and `priority` must be one of the supported enum values.
- Dates must be valid ISO `YYYY-MM-DD` values.
- Invalid input returns `422`; missing entities return `404`; illegal status
  transitions return `409`.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

Install dependencies:

```bash
uv sync
```

Run the API (available at `http://127.0.0.1:8000`, docs at `/docs`):

```bash
uv run uvicorn assistant.main:app --reload
```

Run tests (uses an isolated in-memory database, never the local `assistant.db`):

```bash
uv run pytest
```

Run the linter:

```bash
uv run ruff check .
```

Run the type checker:

```bash
uv run mypy src
```

### Configuration

Copy `.env.example` to `.env` and adjust values as needed:

```bash
cp .env.example .env
```

Available settings: `APP_NAME`, `ENVIRONMENT`, `DATABASE_URL`, `LOG_LEVEL`.
