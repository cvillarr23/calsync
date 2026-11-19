"""Rendering a source's matched events as an iCalendar feed."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from icalendar import Calendar
from icalendar import Event as IcsEvent

from app.db.models import Event, Source
from app.settings import Settings

PRODID = "-//calsync//calsync//EN"
DEFAULT_DURATION = timedelta(hours=1)
"""Used when an adapter gives no end time; a zero-length event hides in most calendar apps."""


def feed_url(settings: Settings, feed_token: str) -> str:
    return f"{str(settings.base_url).rstrip('/')}/feeds/{feed_token}.ics"


def render_calendar(source: Source, events: Sequence[Event], now: datetime) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", source.name)
    for event in events:
        calendar.add_component(_ics_event(source, event, now))
    return calendar.to_ical()


def ics_uid(source: Source, event: Event) -> str:
    """Stable across runs, and unique across sources that list the same event."""
    return f"{source.id}-{event.uid}@calsync"


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
