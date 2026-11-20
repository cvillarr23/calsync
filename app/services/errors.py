"""Errors services raise for the caller to show: the API maps them to HTTP, the UI to pages."""

from app.services.source_validation import Problem


class ServiceError(Exception):
    """Base for errors a user can act on; the message is shown as is."""


class NotFound(ServiceError):
    """The thing doesn't exist, or belongs to another user."""


class Conflict(ServiceError):
    """The change clashes with existing state, e.g. a taken id."""


class Invalid(ServiceError):
    """Input failed validation; `problems` are `{"loc", "msg"}` rows."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(f"{p['loc']}: {p['msg']}" for p in problems))
        self.problems = problems
