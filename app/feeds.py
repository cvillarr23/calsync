"""The `.ics` feed: a source's matched upcoming events, readable by anyone with the token.

There is no login on this route. The unguessable token in the URL is the
access control, so calendar apps can subscribe without credentials.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, status
from icalendar import Calendar
from icalendar import Event as IcsEvent
from sqlalchemy import select

from app.db import Db, Event, Source, utcnow
from app.settings import Settings
from app.sync import matched_events

PRODID = "-//calsync//calsync//EN"
DEFAULT_DURATION = timedelta(hours=1)
"""Used when an adapter gives no end time; a zero-length event hides in most calendar apps."""

router = APIRouter()


def feed_url(settings: Settings, feed_token: str) -> str:
    return f"{str(settings.base_url).rstrip('/')}/feeds/{feed_token}.ics"


@router.get("/feeds/{feed_token}.ics")
def feed(feed_token: str, db: Db) -> Response:
    source = db.scalar(select(Source).where(Source.feed_token == feed_token))
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feed not found")
    now = utcnow()
    body = render_calendar(source, matched_events(db, source, now), now)
    return Response(body, media_type="text/calendar; charset=utf-8")


def render_calendar(source: Source, events: Sequence[Event], now: datetime) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", source.name)
    for event in events:
        calendar.add_component(_ics_event(source, event, now))
    return calendar.to_ical()


def _ics_event(source: Source, event: Event, now: datetime) -> IcsEvent:
    item = IcsEvent()
    item.add("uid", ics_uid(source, event))
    item.add("dtstamp", now)
    item.add("summary", event.title)
    item.add("dtstart", event.start_utc)
    item.add("dtend", event.end_utc or event.start_utc + DEFAULT_DURATION)
    for name, value in (("location", event.location), ("description", event.description)):
        if value:
            item.add(name, value)
    if event.url:
        item.add("url", event.url)
    return item


def ics_uid(source: Source, event: Event) -> str:
    """Stable across runs, and unique across sources that list the same event."""
    return f"{source.id}-{event.uid}@calsync"
