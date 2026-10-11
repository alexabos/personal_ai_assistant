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
from assistant.services.calendar_service import CalendarEvent
from assistant.services.errors import CalendarServiceError, NotionServiceError
from assistant.services.notion_service import NotionTask
from assistant.services.schedule_service import ProposedSchedule
from assistant.tools import calendar_tools, notion_tools, schedule_tools
from assistant.tools.calendar_tools import CALENDAR_TOOLS
from assistant.tools.notion_tools import NOTION_TOOLS
from assistant.tools.planning_tools import PLANNING_TOOLS
from assistant.tools.schedule_tools import SCHEDULE_TOOLS

ALL_TOOLS = PLANNING_TOOLS + CALENDAR_TOOLS + NOTION_TOOLS + SCHEDULE_TOOLS


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


def test_run_turn_without_history_does_not_carry_context(db_session: Session) -> None:
    first_client = ScriptedLLMClient(
        [FakeMessage(stop_reason="end_turn", content=[FakeTextBlock(text="Sure, noted.")])]
    )
    run_turn(
        db_session, "My favorite color is blue.", tools=PLANNING_TOOLS, llm_client=first_client
    )

    second_client = ScriptedLLMClient(
        [FakeMessage(stop_reason="end_turn", content=[FakeTextBlock(text="I don't know.")])]
    )
    run_turn(
        db_session, "What's my favorite color?", tools=PLANNING_TOOLS, llm_client=second_client
    )

    # No history was passed, so the second call's request has only its own message.
    assert len(second_client.sent_messages[0]) == 1


def test_run_turn_with_history_carries_context_across_calls(db_session: Session) -> None:
    history: list[dict] = []

    first_client = ScriptedLLMClient(
        [FakeMessage(stop_reason="end_turn", content=[FakeTextBlock(text="Sure, noted.")])]
    )
    answer1 = run_turn(
        db_session,
        "My favorite color is blue.",
        tools=PLANNING_TOOLS,
        llm_client=first_client,
        history=history,
    )

    assert answer1 == "Sure, noted."
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "My favorite color is blue."}
    assert history[1]["role"] == "assistant"

    second_client = ScriptedLLMClient(
        [FakeMessage(stop_reason="end_turn", content=[FakeTextBlock(text="Blue.")])]
    )
    answer2 = run_turn(
        db_session,
        "What's my favorite color?",
        tools=PLANNING_TOOLS,
        llm_client=second_client,
        history=history,
    )

    assert answer2 == "Blue."
    # sent_messages[0] is the same list object run_turn later appends the
    # final assistant reply to, so [-1] is that reply, not the user message.
    sent_to_second_client = second_client.sent_messages[0]
    assert sent_to_second_client[0]["content"] == "My favorite color is blue."
    assert sent_to_second_client[-2]["content"] == "What's my favorite color?"
    assert len(history) == 4


def test_run_turn_failed_turn_does_not_modify_history(db_session: Session) -> None:
    history: list[dict] = [{"role": "user", "content": "earlier message"}]
    responses = [
        FakeMessage(
            stop_reason="tool_use",
            content=[FakeToolUseBlock(id=f"call_{i}", name="get_daily_plan", input={})],
        )
        for i in range(10)
    ]
    client = ScriptedLLMClient(responses)

    with pytest.raises(ToolExecutionError):
        run_turn(
            db_session, "Loop forever", tools=PLANNING_TOOLS, llm_client=client, history=history
        )

    assert history == [{"role": "user", "content": "earlier message"}]


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


def test_run_turn_selects_list_calendar_events_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="list_calendar_events",
                        input={
                            "start_datetime": "2026-09-24T00:00:00+02:00",
                            "end_datetime": "2026-09-25T00:00:00+02:00",
                        },
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="You have nothing scheduled tomorrow.")],
            ),
        ]
    )

    def fake_list_events(start: object, end: object, **kwargs: object) -> list[object]:
        return []

    original = calendar_tools.calendar_service.list_events
    calendar_tools.calendar_service.list_events = fake_list_events
    try:
        answer = run_turn(
            db_session, "What do I have tomorrow?", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        calendar_tools.calendar_service.list_events = original

    assert answer == "You have nothing scheduled tomorrow."
    tool_result_message = client.sent_messages[1][-1]
    assert "is_error" not in tool_result_message["content"][0]


def test_run_turn_selects_create_calendar_event_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="create_calendar_event",
                        input={
                            "title": "Team meeting",
                            "start_datetime": "2026-09-24T10:00:00+02:00",
                            "end_datetime": "2026-09-24T11:00:00+02:00",
                        },
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="Done - Team meeting is on your calendar.")],
            ),
        ]
    )

    def fake_create_event(title: str, start: object, end: object, **kwargs: object) -> object:
        return CalendarEvent(id="evt-1", title=title, start=start, end=end)  # type: ignore[arg-type]

    original = calendar_tools.calendar_service.create_event
    calendar_tools.calendar_service.create_event = fake_create_event
    try:
        answer = run_turn(
            db_session,
            "Add a meeting tomorrow at 10:00 called Team meeting.",
            tools=ALL_TOOLS,
            llm_client=client,
        )
    finally:
        calendar_tools.calendar_service.create_event = original

    assert answer == "Done - Team meeting is on your calendar."
    tool_result_message = client.sent_messages[1][-1]
    assert "is_error" not in tool_result_message["content"][0]


def test_run_turn_does_not_claim_success_when_calendar_tool_fails(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="create_calendar_event",
                        input={
                            "title": "Team meeting",
                            "start_datetime": "2026-09-24T10:00:00+02:00",
                            "end_datetime": "2026-09-24T11:00:00+02:00",
                        },
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[
                    FakeTextBlock(
                        text="I couldn't create that event - Google Calendar isn't connected."
                    )
                ],
            ),
        ]
    )

    def fake_create_event(*args: object, **kwargs: object) -> object:
        raise CalendarServiceError("Google Calendar is not authenticated yet.")

    original = calendar_tools.calendar_service.create_event
    calendar_tools.calendar_service.create_event = fake_create_event
    try:
        answer = run_turn(
            db_session,
            "Add a meeting tomorrow at 10:00 called Team meeting.",
            tools=ALL_TOOLS,
            llm_client=client,
        )
    finally:
        calendar_tools.calendar_service.create_event = original

    assert "couldn't create" in answer.lower() or "not" in answer.lower()
    tool_result_message = client.sent_messages[1][-1]
    assert tool_result_message["content"][0]["is_error"] is True


def test_run_turn_selects_list_notion_tasks_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1", name="list_notion_tasks", input={"source": "sanofi"}
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="You have one pending Sanofi task.")],
            ),
        ]
    )

    def fake_list_tasks(**kwargs: object) -> list[NotionTask]:
        return [NotionTask(id="p1", title="Finish report", source="sanofi")]

    original = notion_tools.notion_service.list_tasks
    notion_tools.notion_service.list_tasks = fake_list_tasks
    try:
        answer = run_turn(
            db_session, "Show me my Sanofi tasks", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        notion_tools.notion_service.list_tasks = original

    assert answer == "You have one pending Sanofi task."
    tool_result_message = client.sent_messages[1][-1]
    assert "is_error" not in tool_result_message["content"][0]


def test_run_turn_selects_create_notion_task_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="create_notion_task",
                        input={"source": "personal", "title": "Buy milk"},
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="Added 'Buy milk' to your personal tasks.")],
            ),
        ]
    )

    def fake_create_task(source: str, title: str, **kwargs: object) -> NotionTask:
        return NotionTask(id="new-1", title=title, source=source)

    original = notion_tools.notion_service.create_task
    notion_tools.notion_service.create_task = fake_create_task
    try:
        answer = run_turn(
            db_session, "Add a task to buy milk in personal", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        notion_tools.notion_service.create_task = original

    assert answer == "Added 'Buy milk' to your personal tasks."
    tool_result_message = client.sent_messages[1][-1]
    assert "is_error" not in tool_result_message["content"][0]


def test_run_turn_does_not_claim_success_when_notion_tool_fails(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="create_notion_task",
                        input={"source": "personal", "title": "Buy milk"},
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[
                    FakeTextBlock(text="I couldn't create that task - Notion isn't configured.")
                ],
            ),
        ]
    )

    def fake_create_task(*args: object, **kwargs: object) -> NotionTask:
        raise NotionServiceError("Notion is not configured.")

    original = notion_tools.notion_service.create_task
    notion_tools.notion_service.create_task = fake_create_task
    try:
        answer = run_turn(
            db_session, "Add a task to buy milk in personal", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        notion_tools.notion_service.create_task = original

    assert "couldn't create" in answer.lower() or "not" in answer.lower()
    tool_result_message = client.sent_messages[1][-1]
    assert tool_result_message["content"][0]["is_error"] is True


def test_run_turn_selects_propose_schedule_tool(db_session: Session) -> None:
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="propose_schedule",
                        input={
                            "start_datetime": "2026-10-09T14:00:00+02:00",
                            "end_datetime": "2026-10-09T18:00:00+02:00",
                        },
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="I'd suggest starting with the Sanofi report.")],
            ),
        ]
    )

    def fake_build_schedule(start: object, end: object, **kwargs: object) -> ProposedSchedule:
        return ProposedSchedule(range_start=start, range_end=end, scheduled=[], unscheduled=[])  # type: ignore[arg-type]

    original = schedule_tools.schedule_service.build_schedule
    schedule_tools.schedule_service.build_schedule = fake_build_schedule
    try:
        answer = run_turn(
            db_session, "What should I do this afternoon?", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        schedule_tools.schedule_service.build_schedule = original

    assert answer == "I'd suggest starting with the Sanofi report."
    tool_result_message = client.sent_messages[1][-1]
    assert "is_error" not in tool_result_message["content"][0]


def test_run_turn_propose_schedule_never_triggers_create_calendar_event(
    db_session: Session,
) -> None:
    """Structural safety check: the orchestrator only calls the tool(s) the
    LLM explicitly requests in a turn - proposing a schedule in one tool
    call never implicitly chains into creating a calendar event."""
    client = ScriptedLLMClient(
        [
            FakeMessage(
                stop_reason="tool_use",
                content=[
                    FakeToolUseBlock(
                        id="call_1",
                        name="propose_schedule",
                        input={
                            "start_datetime": "2026-10-09T14:00:00+02:00",
                            "end_datetime": "2026-10-09T18:00:00+02:00",
                        },
                    )
                ],
            ),
            FakeMessage(
                stop_reason="end_turn",
                content=[FakeTextBlock(text="Here's a draft plan for your afternoon.")],
            ),
        ]
    )

    def fake_build_schedule(start: object, end: object, **kwargs: object) -> ProposedSchedule:
        return ProposedSchedule(range_start=start, range_end=end, scheduled=[], unscheduled=[])  # type: ignore[arg-type]

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("create_calendar_event must not be called automatically")

    original_build = schedule_tools.schedule_service.build_schedule
    original_create = calendar_tools.calendar_service.create_event
    schedule_tools.schedule_service.build_schedule = fake_build_schedule
    calendar_tools.calendar_service.create_event = fail_if_called
    try:
        run_turn(
            db_session, "What should I do this afternoon?", tools=ALL_TOOLS, llm_client=client
        )
    finally:
        schedule_tools.schedule_service.build_schedule = original_build
        calendar_tools.calendar_service.create_event = original_create
