"""Tests for the tool-calling loop, using a fake LLM client - no real API calls.

The orchestrator's LLMClient dependency is a Protocol (structural typing),
so these stand-in dataclasses don't need to import anything from the
anthropic SDK - they just need the same shape (.stop_reason, .content with
.type on each block) the orchestrator reads.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.orm import Session

from assistant.agent.orchestrator import ToolExecutionError, run_turn
from assistant.services import task_service
from assistant.tools.planning_tools import PLANNING_TOOLS


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class FakeMessage:
    stop_reason: str
    content: list[Any]


class ScriptedLLMClient:
    """Returns one pre-scripted response per call to send()."""

    def __init__(self, responses: list[FakeMessage]) -> None:
        self._responses = list(responses)
        self.sent_messages: list[list[dict[str, Any]]] = []

    def send(self, *, messages: Any, tools: Any, system: Any) -> FakeMessage:
        self.sent_messages.append(messages)
        return self._responses.pop(0)


def test_run_turn_calls_tool_then_returns_final_text(db_session: Session) -> None:
    task_service.create_task(db_session, title="Task A")
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[FakeToolUseBlock(id="call_1", name="get_daily_plan", input={})],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="You should work on Task A.")],
            ),
        ]
    )

    answer = run_turn(db_session, "What should I do?", tools=PLANNING_TOOLS, llm_client=client)

    assert answer == "You should work on Task A."
    assert len(client.sent_messages) == 2


def test_run_turn_returns_text_immediately_when_no_tool_needed(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [FakeMessage(stop_reason="end_turn", content=[FakeTextBlock(text="Hi there!")])]
    )

    answer = run_turn(db_session, "Hello", tools=PLANNING_TOOLS, llm_client=client)

    assert answer == "Hi there!"
    assert len(client.sent_messages) == 1


def test_run_turn_sends_tool_error_back_for_unknown_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[FakeToolUseBlock(id="call_1", name="not_a_real_tool", input={})],
            ),
            FakeMessage(
                stop_reason="end_turn", content=[FakeTextBlock(text="Sorry about that.")]
            ),
        ]
    )

    answer = run_turn(db_session, "Do something weird", tools=PLANNING_TOOLS, llm_client=client)

    assert answer == "Sorry about that."
    second_call_messages = client.sent_messages[1]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["content"][0]["is_error"] is True


def test_run_turn_sends_tool_error_back_for_invalid_args(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1", name="get_daily_plan", input={"available_minutes": -5}
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn", content=[FakeTextBlock(text="Let me try again.")]
            ),
        ]
    )

    answer = run_turn(db_session, "I have -5 minutes", tools=PLANNING_TOOLS, llm_client=client)

    assert answer == "Let me try again."
    tool_result_message = client.sent_messages[1][-1]
    assert tool_result_message["content"][0]["is_error"] is True


def test_run_turn_raises_after_max_iterations(db_session: Session) -> None:
    responses = [
        FakeMessage(
            stop_reason="tool_use",
            content=[FakeToolUseBlock(id=f"call_{i}", name="get_daily_plan", input={})],
        )
        for i in range(10)
    ]
    client = ScriptedLLMClient(responses)

    with pytest.raises(ToolExecutionError):
        run_turn(db_session, "Loop forever", tools=PLANNING_TOOLS, llm_client=client)
