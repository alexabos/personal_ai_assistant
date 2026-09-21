"""Generic tool abstraction shared by all LLM-callable tools.

A Tool is a deliberate narrowing/translation point between an LLM and a
service: it advertises itself via a small Pydantic args model (which doubles
as its JSON schema for the LLM and as input validation for the LLM's raw,
untrusted arguments), and its handler returns plain JSON-serializable data -
never ORM objects or dataclasses. No FastAPI, no LLM provider details.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Tool:
    """An LLM-callable tool wrapping a single service call."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Session, BaseModel], dict[str, Any]]


def find_tool(tools: list[Tool], name: str) -> Tool | None:
    """Look up a tool by name within a given tool list."""
    return next((tool for tool in tools if tool.name == name), None)
