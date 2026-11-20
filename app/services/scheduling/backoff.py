from datetime import datetime, timedelta

from app.db.models import Source

MAX_BACKOFF = timedelta(hours=24)
"""The longest a failing source waits between tries, unless its own interval is longer."""

_MAX_EXPONENT = 16
"""Past this many failures the cap applies anyway; clamping keeps 2**n small."""


def run_delay(source: Source, min_interval_min: int) -> timedelta:
    """The source's interval, doubled for each consecutive failure and capped.

    A success resets `consecutive_failures`, so the delay drops back to the interval.
    """
    interval = timedelta(minutes=max(source.interval_min, min_interval_min))
    backoff = interval * 2 ** min(source.consecutive_failures, _MAX_EXPONENT)
    return min(backoff, max(interval, MAX_BACKOFF))


def next_run_at(source: Source, now: datetime, min_interval_min: int) -> datetime:
    """When the source is next due: one delay after its last run, and never in the past."""
    if source.last_run_at is None:
        return now
    return max(now, source.last_run_at + run_delay(source, min_interval_min))
