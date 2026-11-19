from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Event, Source
from app.services import filters


def matched_events(db: Session, source: Source, now: datetime) -> list[Event]:
    """Stored events that haven't ended yet and pass the source's filters, soonest first."""
    return filters.apply(_upcoming(db, source, now), source.include_kw, source.exclude_kw)


def _upcoming(db: Session, source: Source, now: datetime) -> list[Event]:
    ends = func.coalesce(Event.end_utc, Event.start_utc)
    query = (
        select(Event)
        .where(Event.source_id == source.id, ends >= now)
        .order_by(Event.start_utc, Event.uid)
    )
    return list(db.scalars(query))
