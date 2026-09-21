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
| `services/` | Business logic, independent of FastAPI | Implemented (task, weekly goal, and planning services) |
| `config/` | Application settings via environment variables | Implemented |
| `agent/` | LLM client + tool-calling orchestration loop | Implemented (CLI-only, no HTTP endpoint yet) |
| `tools/` | LLM-callable tools wrapping existing services | Implemented (`get_daily_plan`) |
| Voice interface | Wake word, STT, TTS | Planned |
| Raspberry Pi client | Hardware integration for always-on voice assistant | Planned |

Responsibilities are kept separated on purpose:

- **ORM models** (`db/models.py`) define persistence only.
- **Pydantic schemas** (`schemas/`) define API input/output validation and serialization.
- **Services** (`services/`) contain all business logic (state transitions, filtering,
  normalization). They take a SQLAlchemy `Session` and plain arguments, return ORM
  objects, and raise plain Python exceptions (`services/errors.py`) — no FastAPI
  dependency. This keeps them directly reusable as LLM tool-calling targets.
- **API routes** (`api/routes/`) handle HTTP concerns only: request/response
  shaping and translating service exceptions into HTTP status codes (via global
  exception handlers registered in `main.py`).
- **Tools** (`tools/`) are thin, LLM-facing translators: each one validates the
  LLM's raw arguments via a small Pydantic model, calls straight into an
  existing service, and returns plain JSON — no business logic of its own.
- **Agent** (`agent/`) is the LLM client (`llm_client.py`, the only file that
  knows the provider's wire format) plus the tool-calling loop
  (`orchestrator.py`). Framework-agnostic — no FastAPI. The LLM never touches
  SQLAlchemy or the database directly: `LLM → tools → services → database`.

## Current status

**Phase 4** is complete, building on Phases 1–3 (backend foundation, task/weekly
goal management, deterministic planning). The assistant can now be asked
natural-language questions from a CLI (`scripts/chat.py`), backed by an LLM
(Anthropic Claude) that decides on its own when to call the `get_daily_plan`
tool — which calls the exact same `planning_service.build_daily_plan(...)`
function the `GET /plan` route uses. No new business logic was added; the LLM
only gets a new way to reach the existing one. No voice, Raspberry Pi, or
external integrations (Notion, Google Calendar, etc.) are implemented yet, and
there is no HTTP chat endpoint yet — that's deferred to a later phase once this
architecture is proven out.

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

### Planning

| Method | Path | Description |
|---|---|---|
| `GET` | `/plan` | Deterministic planning snapshot (optional `available_minutes`) |

```bash
curl "http://127.0.0.1:8000/plan?available_minutes=45"
```

Returns:

```json
{
  "reference_date": "2026-09-19",
  "relevant_tasks": [ /* TaskRead, due today or overdue */ ],
  "overdue_tasks": [ /* TaskRead, due date before today */ ],
  "goals_falling_behind": [ /* WeeklyGoalRead, behind a constant weekly pace */ ],
  "suggested_task": /* TaskRead or null: the best task to work on next */
}
```

**Rules (all pure Python, no LLM):**

- **Overdue / relevant today**: a task counts if it isn't `completed` or
  `cancelled` and has a `due_date`. Overdue = due date before today. Relevant
  today = due today or overdue.
- **Goals falling behind**: only `active` goals whose target week is the one
  currently in progress (`week_start <= today <= week_start + 6 days`) and
  that have a `target_minutes` set (goals without one can't be measured, so
  they're skipped). A goal is flagged if `completed_minutes` is below what a
  constant daily pace would predict by now — no tolerance is applied.
- **Suggested next task**: among active, non-cancelled tasks, ranked overdue
  first, then by priority (`high` > `medium` > `low`), then soonest due date,
  then oldest first. If `available_minutes` is given, a task is only
  considered if `estimated_minutes` is set **and** fits the budget — a task
  with an unknown duration is not assumed to fit. If `available_minutes` is
  omitted, tasks with an unknown duration are still eligible.

This is intentionally the only planning endpoint. The underlying service
functions (`list_overdue_tasks`, `list_relevant_tasks`,
`list_goals_falling_behind`, `suggest_next_task`, `build_daily_plan` in
`services/planning_service.py`) are independently callable and are reused
as-is by the Phase 4 `get_daily_plan` tool — see below.

### Validation summary

- Task and goal titles cannot be empty or whitespace-only.
- `estimated_minutes` and `target_minutes` must be positive when provided.
- `completed_minutes` must be non-negative.
- `status` and `priority` must be one of the supported enum values.
- Dates must be valid ISO `YYYY-MM-DD` values.
- Invalid input returns `422`; missing entities return `404`; illegal status
  transitions return `409`.

## LLM assistant (Phase 4)

The assistant can be reached with natural language via a CLI:

```bash
uv run python scripts/chat.py
```

```
Personal AI Assistant (Phase 4 CLI). Type 'exit' to quit.
> What should I do now? I have 45 minutes.
You have one overdue task, "Finish report" — it fits in 45 minutes and is
high priority, so I'd start there.
```

Each line is answered as an independent question — Phase 4 deliberately does
not keep conversation history between turns (no memory yet, by design).

**How it works:** `LLM → tool → service → database`.

1. `agent/orchestrator.py` sends the user's message, plus the list of
   available tools, to the LLM (`agent/llm_client.py` — the only file that
   knows this is Anthropic; everything else is provider-agnostic).
2. If the LLM decides it needs data, it requests a tool by name with some
   arguments — it never touches SQLAlchemy or the database itself.
3. The orchestrator validates those arguments against the tool's small
   Pydantic model (`tools/planning_tools.py`) and calls the tool's handler.
4. The handler calls `planning_service.build_daily_plan(...)` — the same
   function `GET /plan` calls — and converts the result to JSON via the
   existing `DailyPlanRead` schema. No planning rule is duplicated.
5. The JSON result is sent back to the LLM, which produces the final
   natural-language answer.

This loop repeats up to `LLM_MAX_TOOL_ITERATIONS` times per question (default
4) as a safety cap against runaway tool calls.

**Available tools:**

| Tool | Wraps | Description |
|---|---|---|
| `get_daily_plan` | `planning_service.build_daily_plan` | Same data as `GET /plan`: relevant/overdue tasks, goals falling behind, a suggested next task |

**Provider:** Anthropic Claude, via the official `anthropic` SDK. Model id is
configured, not hard-coded — see `LLM_MODEL` below. Default: `claude-sonnet-5`,
chosen to balance cost/latency against Opus-tier models for what is currently
a single, simple tool-routing decision; revisit toward Opus if the assistant
takes on harder multi-step reasoning later, or toward Haiku if cost becomes
the binding constraint once usage is understood.

**Testing:** `tests/test_tools_planning.py` and `tests/test_orchestrator.py`
run fully offline — the orchestrator's LLM client is a `Protocol`, so tests
substitute a scripted fake instead of calling the real API. One additional
test, `tests/test_llm_live.py`, makes a real (billed) call to Anthropic and is
skipped unless `LLM_API_KEY` is set:

```bash
LLM_API_KEY=sk-... uv run pytest tests/test_llm_live.py -v
```

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

Available settings: `APP_NAME`, `ENVIRONMENT`, `DATABASE_URL`, `LOG_LEVEL`,
`LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_TOOL_ITERATIONS`.

`LLM_API_KEY` can be left unset to fall back to the Anthropic SDK's own
credential detection (`ANTHROPIC_API_KEY` env var, or an `ant auth login`
profile).
