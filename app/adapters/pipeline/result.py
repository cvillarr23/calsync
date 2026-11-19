from dataclasses import dataclass, field

from app.adapters.events import ScrapedEvent


@dataclass(frozen=True)
class ItemProblem:
    """A field that couldn't be read from one item; that item was left out."""

    item: int
    field: str
    msg: str

    def __str__(self) -> str:
        return f"item {self.item}: {self.field}: {self.msg}"


@dataclass
class PipelineResult:
    """Everything one pipeline run read, plus the items it had to leave out and why."""

    events: list[ScrapedEvent] = field(default_factory=list)
    problems: list[ItemProblem] = field(default_factory=list)
