"""Business-logic exceptions shared across services.

Kept framework-agnostic on purpose: services (and future LLM tools calling
them directly) should not depend on FastAPI. The API layer is responsible
for translating these into HTTP responses.
"""


class NotFoundError(Exception):
    """Raised when a requested entity does not exist."""


class InvalidStateTransitionError(Exception):
    """Raised when a requested status transition is not allowed."""


class CalendarServiceError(Exception):
    """Raised when a calendar operation is invalid or the Google API fails.

    Covers both input-level problems (e.g. an invalid date range) and
    external failures (missing/expired credentials, Google API errors) -
    callers only need to catch one type to know "the calendar operation
    did not succeed."
    """


class NotionServiceError(Exception):
    """Raised when a Notion operation is invalid or the Notion API fails.

    Covers missing configuration, an unknown source, and external failures
    (API errors) - callers only need to catch one type to know "the Notion
    operation did not succeed."
    """
