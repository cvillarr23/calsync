from dataclasses import dataclass


@dataclass
class SyncResult:
    """What one run did; counts are zero when the run failed before storing."""

    status: str
    error: str | None = None
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    matched: int = 0
