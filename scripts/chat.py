"""Manual CLI to try the assistant's LLM + tool-calling loop.

Run with:
    uv run python scripts/chat.py

Conversation history is kept for the duration of this CLI session (so
follow-ups like "in my main calendar then" work), but is not persisted
anywhere - it is lost when you exit (see README).
"""

from typing import Any

from assistant.agent.orchestrator import run_turn
from assistant.db.database import SessionLocal, init_db
from assistant.tools.calendar_tools import CALENDAR_TOOLS
from assistant.tools.notion_tools import NOTION_TOOLS
from assistant.tools.planning_tools import PLANNING_TOOLS
from assistant.tools.schedule_tools import SCHEDULE_TOOLS

ALL_TOOLS = PLANNING_TOOLS + CALENDAR_TOOLS + NOTION_TOOLS + SCHEDULE_TOOLS


def main() -> None:
    init_db()
    print("Personal AI Assistant CLI. Type 'exit' to quit.")
    history: list[dict[str, Any]] = []
    while True:
        try:
            user_message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_message or user_message.lower() in {"exit", "quit"}:
            break

        db = SessionLocal()
        try:
            answer = run_turn(db, user_message, tools=ALL_TOOLS, history=history)
        finally:
            db.close()
        print(answer)


if __name__ == "__main__":
    main()
