from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True)
class Window:
    """The dates a run covers, from `start` to `end` inclusive."""

    start: date
    end: date

    @classmethod
    def between(cls, start: datetime, end: datetime) -> "Window":
        """The window for the runner contract's `window_start` and `window_end`."""
        return cls(start=start.date(), end=end.date())

    @property
    def base(self) -> datetime:
        """What relative and year-less dates are read against."""
        return datetime.combine(self.start, time())
