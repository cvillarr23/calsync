from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.db.models import Event, Source
from app.services.sync.hashing import content_hash
from app.services.sync.result import SyncResult


def store_events(
    db: Session, source: Source, scraped: list[ScrapedEvent], now: datetime
) -> SyncResult:
    """Upsert this run's events and drop future events the site no longer lists.

    The caller runs this in a savepoint, so a bad event leaves the stored set untouched.
    """
    result = SyncResult(status="ok", fetched=len(scraped))
    existing = {event.uid: event for event in _stored(db, source)}
    if not scraped and any(event.start_utc >= now for event in existing.values()):
        raise AdapterRunError(
            "the adapter returned no events, so nothing was removed; "
            "check the site or the definition"
        )
    fresh = _dedupe(scraped)
    for item in fresh.values():
        _upsert(db, source, existing.get(item.uid), item, now, result)
    for event in _vanished(existing, fresh, now):
        db.delete(event)
        result.removed += 1
    db.flush()
    return result


def _stored(db: Session, source: Source) -> Iterable[Event]:
    return db.scalars(select(Event).where(Event.source_id == source.id))


def _dedupe(scraped: list[ScrapedEvent]) -> dict[str, ScrapedEvent]:
    """One event per uid; the first occurrence wins, as overlapping pages repeat events."""
    unique: dict[str, ScrapedEvent] = {}
    for item in scraped:
        unique.setdefault(item.uid, item)
    return unique


def _upsert(
    db: Session,
    source: Source,
    current: Event | None,
    item: ScrapedEvent,
    now: datetime,
    result: SyncResult,
) -> None:
    digest = content_hash(item)
    if current is None:
        db.add(Event(source_id=source.id, uid=item.uid, **_columns(item, digest, now)))
        result.inserted += 1
    elif current.content_hash != digest:
        _assign(current, _columns(item, digest, now))
        result.updated += 1
    else:
        current.last_seen_at = now
        result.unchanged += 1


def _columns(item: ScrapedEvent, digest: str, now: datetime) -> dict[str, Any]:
    _require_aware(item)
    return {
        "title": item.title,
        "start_utc": item.start_utc,
        "end_utc": item.end_utc,
        "location": item.location,
        "description": item.description,
        "url": item.url,
        "content_hash": digest,
        "last_seen_at": now,
    }


def _require_aware(item: ScrapedEvent) -> None:
    for value in (item.start_utc, item.end_utc):
        if value is not None and value.tzinfo is None:
            raise AdapterRunError(f"event {item.uid!r} has a datetime without a time zone")


def _assign(event: Event, columns: Mapping[str, Any]) -> None:
    for name, value in columns.items():
        setattr(event, name, value)


def _vanished(
    existing: Mapping[str, Event], fresh: Mapping[str, ScrapedEvent], now: datetime
) -> list[Event]:
    """Stored future events missing from this run. Past events are history and stay."""
    return [event for uid, event in existing.items() if uid not in fresh and event.start_utc >= now]
