"""Thin wrapper around the Anthropic Messages API.

This is the only file in the project that knows about the LLM provider's
wire format (tool JSON schema shape, message roles, the SDK itself). The
orchestrator and tools never import `anthropic` directly - if the provider
ever changes, this is the only file that should need to change.
"""

from typing import Any, Protocol

import anthropic

from assistant.config.settings import get_settings
from assistant.tools.registry import Tool


class LLMClient(Protocol):
    """What the orchestrator needs from an LLM client - real or fake.

    Defined as a Protocol (structural typing) so tests can substitute a
    stub client without inheriting from anything or hitting the network.
    """

    def send(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[Tool],
        system: str,
    ) -> anthropic.types.Message: ...


class AnthropicLLMClient:
    """Sends requests to the real Anthropic Messages API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.llm_api_key)
        self._model = settings.llm_model

    def send(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[Tool],
        system: str,
    ) -> anthropic.types.Message:
        api_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.args_model.model_json_schema(),
            }
            for tool in tools
        ]
        # Plain dicts are the deliberate provider-agnostic "wire format" the
        # rest of the app builds; this is the one place they meet the SDK's
        # precise param types.
        return self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            tools=api_tools,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )
