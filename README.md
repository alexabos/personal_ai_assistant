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
| `tools/` | LLM-callable tools wrapping existing services | Implemented (planning, calendar, and Notion tools) |
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
  SQLAlchemy, the database, or any external API directly:
  `LLM → tools → services → database / external API`.
- **Calendar service** (`services/calendar_service.py`) owns all Google
  Calendar API and OAuth logic, following the same framework-agnostic,
  plain-function style as `task_service.py` — the only difference is that
  instead of a SQLAlchemy `Session`, its functions take an optional injected
  Google API client (for tests), defaulting to the real authenticated one.
  It never starts an interactive login itself; see **Authentication** below.
- **Notion service** (`services/notion_service.py`) owns all Notion API logic,
  same plain-function/injected-client style as `calendar_service.py`. It is
  deliberately **independent from the SQLite task service** — Notion is an
  external task/deadline source, never synchronized with or copied into
  SQLite. Multiple Notion databases are supported as separate logical
  "sources" (e.g. `university`, `sanofi`, `personal`); they are never
  merged into one database, only presented through one unified `list_tasks`
  interface. See **Notion setup** below.

## Current status

**Phase 5.2** is complete, building on Phases 1–5.1 (backend foundation,
task/weekly goal management, deterministic planning, LLM tool-calling,
Google Calendar). The assistant can now list, create, and update tasks
across multiple separate Notion databases via natural language, e.g. "Show
me my Sanofi tasks" or "Add a task to buy milk in personal." As with the
other tools, no business logic lives in the agent/tool layer —
`notion_service.py` owns every Notion API detail. No voice, Raspberry Pi
work, or automatic Calendar scheduling yet, and there is still no HTTP chat
endpoint — all remain deferred to later phases. The next planned step is a
combined Calendar + Notion planning workflow that only *proposes* a plan,
without creating anything automatically.

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

## LLM assistant

The assistant can be reached with natural language via a CLI:

```bash
uv run python scripts/chat.py
```

```
Personal AI Assistant CLI. Type 'exit' to quit.
> What should I do now? I have 45 minutes.
You have one overdue task, "Finish report" — it fits in 45 minutes and is
high priority, so I'd start there.
> What do I have tomorrow?
You have a 10:00 team meeting and nothing else scheduled.
```

Conversation history is kept for the lifetime of one CLI session — so
follow-ups like "in my main calendar then" work — but it is **not**
persisted anywhere: closing and reopening `scripts/chat.py` starts fresh.
`run_turn()` itself is stateless by default (no memory of prior turns);
`scripts/chat.py` opts into history by passing a `history` list it owns,
which `run_turn` reads and appends to in place. Persistent, cross-session
memory is a bigger feature deliberately left for a future phase.

**How it works:** `LLM → tool → service → database / external API`.

1. `agent/orchestrator.py` sends the user's message, plus the current
   date/time and the list of available tools, to the LLM
   (`agent/llm_client.py` — the only file that knows this is Anthropic;
   everything else is provider-agnostic).
2. If the LLM decides it needs data or wants to take an action, it requests a
   tool by name with some arguments — it never touches SQLAlchemy, the
   database, or the Google Calendar API itself.
3. The orchestrator validates those arguments against the tool's small
   Pydantic model and calls the tool's handler.
4. The handler calls straight into an existing service (`planning_service.py`
   or `calendar_service.py`) — the same functions the `GET /plan` route and
   any future callers use — and converts the result to plain JSON. No
   business logic is duplicated in the tool layer.
5. The JSON result is sent back to the LLM, which produces the final
   natural-language answer. If the service raised an error, the LLM receives
   it as a failed tool call and must not report success.

This loop repeats up to `LLM_MAX_TOOL_ITERATIONS` times per question (default
4) as a safety cap against runaway tool calls.

**Available tools:**

| Tool | Wraps | Description |
|---|---|---|
| `get_daily_plan` | `planning_service.build_daily_plan` | Same data as `GET /plan`: relevant/overdue tasks, goals falling behind, a suggested next task |
| `list_calendar_events` | `calendar_service.list_events` | Events starting within a given timezone-aware range |
| `create_calendar_event` | `calendar_service.create_event` | Creates an event, optionally on a named calendar (main or shared) and/or with a color; never reported as created unless the API call actually succeeded |
| `list_notion_tasks` | `notion_service.list_tasks` | Tasks from one configured Notion source, or all of them (`source="all"`, the default) |
| `create_notion_task` | `notion_service.create_task` | Creates a task in one named source — never an arbitrary database ID |
| `update_notion_task` | `notion_service.update_task` | Updates a task's title/priority/status/deadline/category by its Notion page ID |

**Provider:** Anthropic Claude, via the official `anthropic` SDK. Model id is
configured, not hard-coded — see `LLM_MODEL` below. Default: `claude-sonnet-5`,
chosen to balance cost/latency against Opus-tier models for what is currently
simple tool-routing decisions; revisit toward Opus if the assistant takes on
harder multi-step reasoning later, or toward Haiku if cost becomes the
binding constraint once usage is understood.

**Testing:** `tests/test_tools_planning.py`, `tests/test_tools_calendar.py`,
`tests/test_calendar_service.py`, `tests/test_notion_service.py`,
`tests/test_notion_tools.py`, and `tests/test_orchestrator.py` run fully
offline — the orchestrator's LLM client is a `Protocol`, so tests substitute
a scripted fake instead of calling the real API, and the calendar/Notion
services always receive an injected mock API client in tests, so no test
ever reads real credentials or touches the network. One additional test,
`tests/test_llm_live.py`, makes a real (billed) call to Anthropic and is
skipped unless `LLM_API_KEY` is set:

```bash
LLM_API_KEY=sk-... uv run pytest tests/test_llm_live.py -v
```

### Google Calendar setup

1. **Create a Google Cloud project and enable the Calendar API:**
   - Go to the [Google Cloud Console](https://console.cloud.google.com/),
     create (or select) a project.
   - Navigate to **APIs & Services → Library**, search for "Google Calendar
     API", and enable it.

2. **Create OAuth 2.0 credentials for a personal account:**
   - Navigate to **APIs & Services → Credentials → Create Credentials →
     OAuth client ID**.
   - If prompted, configure the OAuth consent screen first (choose
     **External** and add your own Google account as a test user — this
     project only needs a personal, single-user flow).
   - Choose **Application type: Desktop app**.
   - Download the resulting JSON file.

3. **Place the downloaded file** at the path configured by
   `GOOGLE_CALENDAR_CREDENTIALS_FILE` (default `credentials/google_calendar_credentials.json`).
   The `credentials/` directory is gitignored — never commit this file.

4. **Run the one-time authentication script:**

   ```bash
   uv run python scripts/google_calendar_auth.py
   ```

   This opens a browser for Google's consent screen once, then caches a
   token to `GOOGLE_CALENDAR_TOKEN_FILE` (default
   `credentials/google_calendar_token.json`, also gitignored). Re-run this
   script if the assistant later reports that authentication has expired or
   is missing — **or whenever the requested OAuth scopes change** (see
   `calendar_service.SCOPES`): Google does not let a cached token silently
   gain new permissions, so a scope change always requires re-consenting.

**Listing spans every calendar you have access to** (your main calendar and
any shared calendars), merged and sorted by start time; a calendar that
can't be queried (e.g. restricted access) is skipped rather than failing the
whole request.

**Creating an event targets `GOOGLE_CALENDAR_ID` (default `primary`) unless
you name a different calendar** — e.g. "add it to my Família Rodes Abos
calendar" resolves against your actual Google account's calendar list (exact
match first, then a unique substring match); an unrecognized or ambiguous
name is rejected with a clear error rather than silently falling back to
your main calendar. You can also ask for an event **color**, but only from
Google's fixed palette (`lavender`, `sage`, `grape`, `flamingo`, `banana`,
`tangerine`, `peacock`, `graphite`, `blueberry`, `basil`, `tomato`) — there
is no way to register a custom/personal color name, so the assistant will
ask you to pick one of these instead of guessing.

**Authentication design:** `scripts/google_calendar_auth.py` is the *only*
place in the project that opens an interactive browser flow. During normal
assistant use, `calendar_service.py` never does — if no valid, cached token
exists (or it's expired beyond automatic refresh), it raises a
`CalendarServiceError` explaining that the auth script needs to be run,
rather than blocking the conversation on a login prompt. A token nearing
expiry is refreshed automatically and silently, with no interaction needed.

### Notion setup

1. **Create a Notion internal integration:**
   - Go to [notion.so/my-integrations](https://www.notion.so/my-integrations),
     create a new **internal** integration (no OAuth, just a bearer token —
     this project never does interactive Notion auth).
   - Copy its "Internal Integration Secret" into `NOTION_API_KEY`.

2. **Share each task database with the integration:** open each database in
   Notion, click **"..." → Connections → Connect to**, and select your
   integration. Without this step, Notion returns a 404 for that database
   even with a valid API key.

3. **Configure each database as a named source:** copy the database ID from
   its URL (the 32-character ID segment) into the matching setting:

   ```env
   NOTION_DATABASE_UNIVERSITY=...
   NOTION_DATABASE_SANOFI=...
   NOTION_DATABASE_PERSONAL=...
   ```

   Leave a source unset (blank) to disable it. **Adding a new source later**
   requires one new `Settings` field in `config/settings.py` plus one `.env`
   line — a small, explicit code change, not a config-only one; see
   `notion_service.get_configured_sources()`.

**Expected database schema** (per source): a `Task` title property,
`Priority` (`high`/`medium`/`low`), `Status` (`pending`/`in_progress`/
`completed`/`cancelled`), `Deadline` (date), and `Category` (select/text).
These property names are centralized as constants at the top of
`notion_service.py` — if your real databases use different names, that's a
one-line fix per property, not a redesign.

**`Priority`/`Status`/`Category` can each be either Notion's classic
`select` type or the newer dedicated `status` type** (Notion introduced
`status` specifically for task-tracking properties, and different
databases — even your own, created at different times — may use different
types for the same-looking property). Reading already handled both
transparently; writing (create/update) looks up each property's actual
type from the database's live schema before sending the write, since
Notion rejects a write using the wrong one. This costs one extra API call
per write when a select-like property is involved, only when needed.

**Sources stay separate, never merged into one database.** `list_notion_tasks`
can query one named source or `source="all"`; each returned task carries
its `source` so the assistant (and you) can tell "Prepare university
lecture" apart from "Finish Sanofi analysis" even though both came through
the same unified tool. If any configured source fails to query during
`source="all"`, the whole call fails clearly naming that source — unlike
Calendar's list, it never silently returns partial results.

**Notion is intentionally not synchronized with SQLite.** The existing
`/tasks` API and SQLite task service are untouched; Notion is a separate,
external task source the agent can also consult — nothing is copied or
duplicated between the two systems.

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
`LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_TOOL_ITERATIONS`,
`GOOGLE_CALENDAR_CREDENTIALS_FILE`, `GOOGLE_CALENDAR_TOKEN_FILE`,
`GOOGLE_CALENDAR_ID`, `DEFAULT_TIMEZONE`, `NOTION_API_KEY`,
`NOTION_DATABASE_UNIVERSITY`, `NOTION_DATABASE_SANOFI`,
`NOTION_DATABASE_PERSONAL`.

`LLM_API_KEY` can be left unset to fall back to the Anthropic SDK's own
credential detection (`ANTHROPIC_API_KEY` env var, or an `ant auth login`
profile). See **Google Calendar setup** and **Notion setup** above for the
respective integration settings.
