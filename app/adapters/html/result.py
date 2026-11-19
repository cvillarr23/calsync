from dataclasses import dataclass, field

from app.adapters.events import ScrapedEvent


@dataclass(frozen=True)
class FieldProblem:
    """A field that couldn't be read from one item; that item was left out."""

    page: str
    item: int
    field: str
    msg: str

    def __str__(self) -> str:
        return f"{self.page} item {self.item}: {self.field}: {self.msg}"


@dataclass
class RunResult:
    """Everything one html run read, plus the items it had to leave out and why."""

    events: list[ScrapedEvent] = field(default_factory=list)
    problems: list[FieldProblem] = field(default_factory=list)
