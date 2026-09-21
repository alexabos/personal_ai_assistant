"""One live integration test against the real Anthropic API.

Skipped by default: requires LLM_API_KEY (a real, billed API call). Run it
explicitly with:

    LLM_API_KEY=sk-... uv run pytest tests/test_llm_live.py -v

The rest of the suite never depends on this - it is fully stubbed.
"""

import os

import pytest
from sqlalchemy.orm import Session

from assistant.agent.orchestrator import run_turn
from assistant.services import task_service
from assistant.tools.planning_tools import PLANNING_TOOLS

pytestmark = pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"), reason="requires a real LLM_API_KEY (live API call)"
)


def test_run_turn_against_real_anthropic_api(db_session: Session) -> None:
    task_service.create_task(
        db_session, title="Write the quarterly report", estimated_minutes=30
    )

    answer = run_turn(db_session, "What should I do? I have 45 minutes.", tools=PLANNING_TOOLS)

    assert isinstance(answer, str)
    assert len(answer) > 0
