from pydantic import BaseModel


class SyncRunOut(BaseModel):
    """What one Sync now did; counts are zero when the run failed before storing."""

    status: str
    error: str | None
    fetched: int
    inserted: int
    updated: int
    unchanged: int
    removed: int
    matched: int
