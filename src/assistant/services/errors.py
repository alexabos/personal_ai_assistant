"""Business-logic exceptions shared across services.

Kept framework-agnostic on purpose: services (and future LLM tools calling
them directly) should not depend on FastAPI. The API layer is responsible
for translating these into HTTP responses.
"""


class NotFoundError(Exception):
    """Raised when a requested entity does not exist."""


class InvalidStateTransitionError(Exception):
    """Raised when a requested status transition is not allowed."""
