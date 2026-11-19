"""One sync run for one source: scrape, store, filter, push to targets, record status.

The run stores every event the adapter returns, matched or not, so changing a
source's filters takes effect without re-scraping. Filtering happens on the
way out: in `matched_events` for the feed and for each sync target.
"""

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import filters
from app.adapters.events import AdapterRunError, AdapterRunner, ScrapedEvent, default_runner
from app.adapters.fetch import FetchError
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition
from app.db import Event, Source, utcnow

log = logging.getLogger(__name__)

_EXPECTED_ERRORS = (AdapterRunError, FetchError)
"""Failures the user can act on; anything else is also logged with a traceback."""


class SyncTarget(Protocol):
    """Somewhere matched events are pushed after they are stored, e.g. a Google Calendar."""

    async def apply(
        self, db: Session, source: Source, matched: Sequence[Event], now: datetime
    ) -> None: ...


@dataclass
class SyncResult:
    status: str
    error: str | None = None
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    matched: int = 0


async def run_source(
    db: Session,
    source: Source,
    *,
    registry: AdapterRegistry,
    runner: AdapterRunner = default_runner,
    targets: Iterable[SyncTarget] = (),
    now: datetime | None = None,
) -> SyncResult:
    """Run one sync and record its outcome on the source. Failures are recorded, not raised."""
    now = now or utcnow()
    try:
        scraped = await _scrape(source, registry, runner, now)
        with db.begin_nested():
            result = _store(db, source, scraped, now)
        matched = matched_events(db, source, now)
        result.matched = len(matched)
        for target in targets:
            await target.apply(db, source, matched, now)
    except Exception as err:
        return _record_failure(source, err, now)
    _record_success(source, now)
    return result


def matched_events(db: Session, source: Source, now: datetime) -> list[Event]:
    """Stored events that haven't ended yet and pass the source's filters, soonest first."""
    return filters.apply(_upcoming(db, source, now), source.include_kw, source.exclude_kw)


def content_hash(event: ScrapedEvent) -> str:
    """A stable hash of everything a calendar shows, so unchanged events can be skipped."""
    fields = {
        "title": event.title,
        "start": event.start_utc.isoformat(),
        "end": event.end_utc.isoformat() if event.end_utc else None,
        "location": event.location,
        "description": event.description,
        "url": event.url,
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _scrape(
    source: Source, registry: AdapterRegistry, runner: AdapterRunner, now: datetime
) -> list[ScrapedEvent]:
    definition = registry.get(source.adapter_id)
    if definition is None:
        raise AdapterRunError(f"adapter {source.adapter_id!r} not found")
    window_end = now + timedelta(days=source.lookahead_days)
    return await runner(definition, _params(definition, source), now, window_end)


def _params(definition: AdapterDefinition, source: Source) -> dict[str, Any]:
    """The source's params over the definition's defaults."""
    defaults = {
        name: param.default
        for name, param in definition.params.items()
        if param.default is not None
    }
    return {**defaults, **source.params_json}


def _store(db: Session, source: Source, scraped: list[ScrapedEvent], now: datetime) -> SyncResult:
    """Upsert this run's events and drop future events the site no longer lists.

    The caller runs this in a savepoint, so a bad event leaves the stored set untouched.
    """
    result = SyncResult(status="ok", fetched=len(scraped))
    existing = {event.uid: event for event in _stored(db, source)}
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


def _upcoming(db: Session, source: Source, now: datetime) -> list[Event]:
    ends = func.coalesce(Event.end_utc, Event.start_utc)
    query = (
        select(Event)
        .where(Event.source_id == source.id, ends >= now)
        .order_by(Event.start_utc, Event.uid)
    )
    return list(db.scalars(query))


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


def _record_success(source: Source, now: datetime) -> None:
    source.last_run_at = now
    source.last_status = "ok"
    source.last_error = None
    source.consecutive_failures = 0


def _record_failure(source: Source, err: Exception, now: datetime) -> SyncResult:
    _log_failure(source, err)
    source.last_run_at = now
    source.last_status = "error"
    source.last_error = str(err) or type(err).__name__
    source.consecutive_failures += 1
    return SyncResult(status="error", error=source.last_error)


def _log_failure(source: Source, err: Exception) -> None:
    if isinstance(err, _EXPECTED_ERRORS):
        log.warning("sync of source %s failed: %s", source.id, err)
    else:
        log.exception("sync of source %s failed unexpectedly", source.id)
