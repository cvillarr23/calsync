"""When a source is due to sync next, for display."""

from datetime import datetime, timedelta

from app.db.models import Source


def estimated_next_run(source: Source) -> datetime | None:
    """`last_run_at + interval_min`; None when disabled or never run.

    This is an estimate until the in-process scheduler owns the timing (and backoff).
    """
    if not source.enabled or source.last_run_at is None:
        return None
    return source.last_run_at + timedelta(minutes=source.interval_min)
