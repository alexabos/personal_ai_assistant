"""The tool-calling loop: coordinates the LLM client and the available tools.

Each call to run_turn handles one user question end-to-end, including any
internal LLM <-> tool round-trips, and returns the final answer. By default
(no `history` argument) a call has no memory of prior turns. A caller that
wants a multi-turn conversation (e.g. scripts/chat.py) passes a persistent
`history` list: it is read for prior context and updated in place with this
turn's messages, so the same list can be passed again on the next call.
Nothing here decides business outcomes - that stays in the services the
tools call.
"""

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from assistant.agent.llm_client import AnthropicLLMClient, LLMClient
from assistant.config.settings import get_settings
from assistant.services.errors import CalendarServiceError, NotionServiceError
from assistant.tools.registry import Tool, find_tool

SYSTEM_PROMPT_TEMPLATE = (
    "You are a personal assistant that helps the user manage tasks, weekly "
    "goals, their Google Calendar, and their Notion tasks. Google Calendar "
    "holds scheduled events (meetings, appointments). Notion holds external "
    "tasks and deadlines, split across multiple separate sources (e.g. work, "
    "university, personal) that are never merged into one - always ask "
    "yourself whether the user means one specific source or all of them. "
    "SQLite (the task/weekly-goal tools) is the assistant's own separate "
    "internal task system, distinct from both. Use the available tools to "
    "look up real data before answering questions about what the user "
    "should do next or what's on their calendar. The current date and time "
    "is {now}, in the user's Europe/Madrid timezone - use this to resolve "
    "relative references such as 'today', 'tomorrow', or 'next Monday'. "
    "When calling calendar tools, always pass timezone-aware ISO-8601 "
    "datetimes with an explicit UTC offset for that timezone, never a naive "
    "datetime. Only report a calendar event or Notion task as created/"
    "updated if the tool result confirms it - never assume or claim "
    "success. For planning questions (e.g. 'what should I do this "
    "afternoon'), use propose_schedule to get a draft that combines real "
    "free Calendar time with ranked Notion tasks - present it as a "
    "suggestion only. Never call create_calendar_event as part of "
    "answering a planning question; only do so if the user separately and "
    "explicitly asks to add something to their calendar afterward. Be "
    "concise."
)


def _build_system_prompt() -> str:
    """Build the system prompt with the current date/time, resolved fresh per turn.

    The LLM has no other way to know "today" - without this, it cannot
    resolve relative dates ("tomorrow", "next Monday") and will ask the user
    to clarify instead of calling a calendar tool.
    """
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.default_timezone))
    return SYSTEM_PROMPT_TEMPLATE.format(now=now.isoformat(timespec="minutes"))


class ToolExecutionError(Exception):
    """Raised when a requested tool cannot be found, or the loop cannot finish."""


def _execute_tool(
    db: Session, tools: list[Tool], name: str, raw_input: dict[str, Any]
) -> dict[str, Any]:
    tool = find_tool(tools, name)
    if tool is None:
        raise ToolExecutionError(f"Unknown tool: {name}")
    args = tool.args_model.model_validate(raw_input)
    return tool.handler(db, args)


def run_turn(
    db: Session,
    user_message: str,
    *,
    tools: list[Tool],
    llm_client: LLMClient | None = None,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Answer one user question, calling tools as needed.

    By default (history=None) each call is independent, with no memory of
    prior turns. Pass a list as `history` to carry conversation context
    across calls: this turn's messages (including the final answer) are
    appended to it in place on success, so the same list can be passed again
    on the next call. A failed turn (max tool-iterations exceeded) does not
    modify `history`.
    """
    settings = get_settings()
    client = llm_client or AnthropicLLMClient()
    messages: list[dict[str, Any]] = list(history) if history is not None else []
    messages.append({"role": "user", "content": user_message})
    system_prompt = _build_system_prompt()

    for _ in range(settings.llm_max_tool_iterations):
        response = client.send(messages=messages, tools=tools, system=system_prompt)

        if response.stop_reason != "tool_use":
            answer = next(
                (block.text for block in response.content if block.type == "text"), ""
            )
            if history is not None:
                messages.append({"role": "assistant", "content": response.content})
                history[:] = messages
            return answer

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = _execute_tool(db, tools, block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            except (
                ToolExecutionError,
                ValidationError,
                CalendarServiceError,
                NotionServiceError,
            ) as exc:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    raise ToolExecutionError("Exceeded max tool-calling iterations without a final answer")
