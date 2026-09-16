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
| `api/` | FastAPI HTTP layer (routes, request/response handling) | Implemented (health check only) |
| `db/` | Database engine, session management, ORM models | Implemented (foundation only, no domain models) |
| `config/` | Application settings via environment variables | Implemented |
| `agent/` | LLM-driven agent orchestration (planning, reasoning) | Planned |
| `tools/` | Agent-callable tools (tasks, calendar, goals, learning) | Planned |
| `services/` | Business logic shared across API and agent layers | Planned (empty scaffold) |
| Voice interface | Wake word, STT, TTS | Planned |
| Raspberry Pi client | Hardware integration for always-on voice assistant | Planned |

## Current status

**Phase 1** is complete: this repository currently contains only the
**repository and backend foundation** — a FastAPI application with a health
check endpoint, application settings, and a SQLite/SQLAlchemy database
foundation (engine, session factory, declarative base). No LLM, agent, tools,
voice, or external integrations (Notion, Google Calendar, etc.) are implemented
yet.

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

Run tests:

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
