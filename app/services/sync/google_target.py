from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, GoogleMap, Source
from app.services.google_calendar import GoogleCalendarClient
from app.services.google_calendar.event_body import event_body, is_ours
from app.services.sync.google_plan import plan_push


class GoogleCalendarTarget:
    """Mirrors a source's matched events into its target Google Calendar.

    Each Google write is committed to `google_map` at once, so no database lock is held
    across HTTP calls. Only events carrying this source's tag are patched or deleted.
    """

    def __init__(self, open_client: Callable[[], GoogleCalendarClient]) -> None:
        self._open_client = open_client

    async def apply(
        self, db: Session, source: Source, matched: Sequence[Event], now: datetime
    ) -> None:
        plan = plan_push(source.target_calendar_id, mapped_rows(db, source), matched, now)
        _forget(db, plan.forget)
        if not plan.calls_google:
            return
        async with self._open_client() as client:
            for row in plan.deletes:
                await _delete(db, client, row)
            for row, event in plan.patches:
                await _patch(db, client, row, event)
            for event in plan.inserts:
                await _insert(db, client, source.target_calendar_id, event)


def mapped_rows(db: Session, source: Source) -> dict[str, GoogleMap]:
    rows = db.scalars(select(GoogleMap).where(GoogleMap.source_id == source.id))
    return {row.uid: row for row in rows}


def _forget(db: Session, rows: Sequence[GoogleMap]) -> None:
    for row in rows:
        db.delete(row)
    db.commit()


async def _delete(db: Session, client: GoogleCalendarClient, row: GoogleMap) -> None:
    """Checked against Google first, so an event that lost its tag is left alone."""
    remote = await client.get_event(row.calendar_id, row.google_event_id)
    if remote is not None and is_ours(remote, row.source_id, row.uid):
        await client.delete_event(row.calendar_id, row.google_event_id)
    db.delete(row)
    db.commit()


async def _patch(db: Session, client: GoogleCalendarClient, row: GoogleMap, event: Event) -> None:
    """An event deleted or re-tagged in Google gets a fresh copy instead of a patch."""
    remote = await client.get_event(row.calendar_id, row.google_event_id)
    ours = remote is not None and is_ours(remote, row.source_id, row.uid)
    if ours and await client.patch_event(row.calendar_id, row.google_event_id, event_body(event)):
        _remember(row, row.google_event_id, event)
        db.commit()
        return
    db.delete(row)
    db.commit()
    await _insert(db, client, row.calendar_id, event)


async def _insert(
    db: Session, client: GoogleCalendarClient, calendar_id: str, event: Event
) -> None:
    google_event_id = await client.insert_event(calendar_id, event_body(event))
    row = GoogleMap(source_id=event.source_id, uid=event.uid, calendar_id=calendar_id)
    _remember(row, google_event_id, event)
    db.add(row)
    db.commit()


def _remember(row: GoogleMap, google_event_id: str, event: Event) -> None:
    row.google_event_id = google_event_id
    row.content_hash = event.content_hash
    row.start_utc = event.start_utc
