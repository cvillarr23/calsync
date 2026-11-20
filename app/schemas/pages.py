"""View models for the web pages: what a template shows, already worked out."""

from dataclasses import dataclass
from datetime import datetime

from app.services.error_hints import Hint


@dataclass(frozen=True)
class SourceRow:
    id: int
    name: str
    adapter_name: str
    enabled: bool
    status: str
    error: str | None
    hint: Hint | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    matched: int
    feed_url: str


@dataclass(frozen=True)
class ProblemRow:
    """A definition validation error, with its YAML line and help when we have some."""

    loc: str
    msg: str
    line: int | None
    hint: Hint | None
