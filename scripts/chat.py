"""Manual CLI to try the assistant's LLM + tool-calling loop.

Run with:
    uv run python scripts/chat.py

Each line you type is answered as an independent question - Phase 4 does not
persist conversation history between turns (see README).
"""

from assistant.agent.orchestrator import run_turn
from assistant.db.database import SessionLocal, init_db
from assistant.tools.planning_tools import PLANNING_TOOLS


def main() -> None:
    init_db()
    print("Personal AI Assistant (Phase 4 CLI). Type 'exit' to quit.")
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
            answer = run_turn(db, user_message, tools=PLANNING_TOOLS)
        finally:
            db.close()
        print(answer)


if __name__ == "__main__":
    main()
