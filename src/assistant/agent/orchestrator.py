"""The tool-calling loop: coordinates the LLM client and the available tools.

Stateless across turns by design (Phase 4 scope - no conversational memory):
each call to run_turn handles one user question end-to-end, including any
internal LLM <-> tool round-trips, and returns the final answer. Nothing here
decides business outcomes - that stays in the services the tools call.
"""

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from assistant.agent.llm_client import AnthropicLLMClient, LLMClient
from assistant.config.settings import get_settings
from assistant.tools.registry import Tool, find_tool

SYSTEM_PROMPT = (
    "You are a personal assistant that helps the user manage tasks and weekly "
    "goals. Use the available tools to look up real data before answering "
    "questions about what the user should do next. Be concise."
)


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
) -> str:
    """Answer one user question, calling tools as needed. Stateless across turns."""
    settings = get_settings()
    client = llm_client or AnthropicLLMClient()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    for _ in range(settings.llm_max_tool_iterations):
        response = client.send(messages=messages, tools=tools, system=SYSTEM_PROMPT)

        if response.stop_reason != "tool_use":
            return next(
                (block.text for block in response.content if block.type == "text"), ""
            )

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
            except (ToolExecutionError, ValidationError) as exc:
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
