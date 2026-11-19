import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from icalendar import Calendar

from app.adapters.events import ScrapedEvent
from app.db import Source
from app.sync import run_source
from tests.adapters.conftest import HTML_DEF
from tests.test_sync import FakeRunner

SOON = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)


def upcoming(uid, title, days, hours=1.5, **extra):
    start = SOON + timedelta(days=days)
    end = start + timedelta(hours=hours) if hours else None
    return ScrapedEvent(uid, title, start, end, **extra)


EVENTS = [
    upcoming("skate-1", "Public Skate", 0, location="Main rink", url="https://rink.example/1"),
    upcoming("theme-1", "Public Skate Theme Night: EDM/House", 1),
    upcoming("hockey-1", "Drop-in Hockey", 2),
    upcoming("skate-2", "Public  skate (no end)", 3, hours=None),
]


@pytest.fixture
def feed_source(client):
    client.post("/api/adapters", json=HTML_DEF)
    body = {
        "name": "UW Public Skate",
        "adapter_id": "rec-center",
        "params": {"url": "https://rink.example/schedule"},
        "include_kw": ["public skate"],
        "exclude_kw": ["theme night"],
    }
    source = client.post("/api/sources", json=body).json()
    _sync(client, source["id"], EVENTS)
    return source


def _sync(client, source_id, events):
    state = client.app.state
    with state.sessions.begin() as db:
        source = db.get(Source, source_id)
        runner = FakeRunner(events)
        result = asyncio.run(run_source(db, source, registry=state.adapters, runner=runner))
    assert result.status == "ok", result.error


def _path(source):
    return source["feed_url"].removeprefix("https://calsync.example")


def test_feed_serves_matched_events_as_valid_ics(client, feed_source):
    response = client.get(_path(feed_source))
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"

    calendar = Calendar.from_ical(response.content)
    events = calendar.walk("VEVENT")
    assert calendar["X-WR-CALNAME"] == "UW Public Skate"
    assert [str(e["SUMMARY"]) for e in events] == ["Public Skate", "Public  skate (no end)"]
    assert str(events[0]["LOCATION"]) == "Main rink"
    assert str(events[0]["URL"]) == "https://rink.example/1"
    assert events[1]["DTEND"].dt - events[1]["DTSTART"].dt == timedelta(hours=1)
    assert Calendar.from_ical(calendar.to_ical()).to_ical() == calendar.to_ical()


def test_feed_uids_are_stable(client, feed_source):
    first = Calendar.from_ical(client.get(_path(feed_source)).content)
    second = Calendar.from_ical(client.get(_path(feed_source)).content)
    uids = [str(e["UID"]) for e in first.walk("VEVENT")]
    assert uids == [str(e["UID"]) for e in second.walk("VEVENT")]
    assert uids == [f"{feed_source['id']}-skate-1@calsync", f"{feed_source['id']}-skate-2@calsync"]


def test_feed_follows_filter_changes(client, feed_source):
    client.patch(f"/api/sources/{feed_source['id']}", json={"include_kw": ["hockey"]})
    calendar = Calendar.from_ical(client.get(_path(feed_source)).content)
    assert [str(e["SUMMARY"]) for e in calendar.walk("VEVENT")] == ["Drop-in Hockey"]


def test_unknown_token_is_404(client):
    assert client.get("/feeds/not-a-token.ics").status_code == 404


def test_feed_needs_no_login(client, feed_source):
    """The token in the URL is the access control; no cookie or header is needed."""
    client.cookies.clear()
    assert client.get(_path(feed_source), headers={}).status_code == 200
