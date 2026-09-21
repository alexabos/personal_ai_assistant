"""LLM-callable tools: thin translators between the LLM and existing services.

Each tool validates the LLM's raw arguments via a small Pydantic model, calls
into an existing service, and returns plain JSON-serializable data. No
business logic lives here - see assistant.services for that.
"""
