"""The Google Calendar push, run through `run_source` against a fake Calendar API."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.adapters.events import ScrapedEvent
from app.adapters.fetch import PageLimitExceeded
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import parse_definition
from app.db.engine import init_db, make_engine
from app.db.models import Event, GoogleMap, Source, User
from app.services.google_calendar import GoogleConnection
from app.services.sync import content_hash, run_source
from app.services.sync.google_targets import google_targets
from app.services.tokens import encrypt_token
from tests.adapters.conftest import HTML_DEF
from tests.support import FakeCalendar, FakeRunner, no_sleep

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)
TARGET = "skate#rink@group.calendar.google.com"
OTHER = "primary@example.com"


def scraped(uid, title, days, **extra):
    start = NOW + timedelta(days=days)
    return ScrapedEvent(uid, title, start, start + timedelta(hours=1), **extra)


SKATES = [
    scraped("skate-1", "Public Skate", 1, location="Main rink"),
    scraped("skate-2", "Public Skate", 2),
    scraped("hockey-1", "Drop-in Hockey", 3),
]


@pytest.fixture
def settings():
    """A key generated per run, so no Fernet-shaped secret is ever written down."""
    return SimpleNamespace(
        google_client_id="placeholder-client-id",
        google_client_secret=SecretStr("placeholder-client-secret"),
        token_enc_key=SecretStr(Fernet.generate_key().decode()),
    )


@pytest.fixture
def calendar():
    return FakeCalendar()


@pytest.fixture
def connection(settings, calendar):
    return GoogleConnection(settings, calendar.transport, no_sleep)


@pytest.fixture
def registry():
    registry = AdapterRegistry()
    registry.add_source(lambda user_id: [parse_definition(HTML_DEF)])
    return registry


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "data")
    yield init_db(engine)
    engine.dispose()


@pytest.fixture
def db(sessions):
    with sessions() as session:
        yield session


@pytest.fixture
def source(db, settings):
    user = User(email="a@example.com", refresh_token_enc=encrypt_token(settings, "refresh-1"))
    db.add(user)
    db.flush()
    source = Source(
        user_id=user.id,
        name="Rink",
        adapter_id="rec-center",
        params_json={"url": "https://rink.example/schedule"},
        include_kw=["public skate"],
        target_calendar_id=TARGET,
    )
    db.add(source)
    db.commit()
    return source


async def sync(db, source, registry, connection, events, now=NOW, **runner_kwargs):
    runner = FakeRunner(events, **runner_kwargs)
    targets = google_targets(connection)(db, source)
    result = await run_source(
        db, source, registry=registry, runner=runner, targets=targets, now=now
    )
    db.commit()
    return result


def mapped(db, source):
    rows = db.scalars(select(GoogleMap).where(GoogleMap.source_id == source.id))
    return {row.uid: row for row in rows}


async def test_matched_events_are_inserted_with_the_calsync_tag(
    db, source, registry, connection, calendar
):
    result = await sync(db, source, registry, connection, SKATES)

    assert result.status == "ok", result.error
    pushed = calendar.tagged(TARGET)
    assert set(pushed) == {"skate-1", "skate-2"}
    skate = pushed["skate-1"]
    assert skate["extendedProperties"]["private"] == {
        "calsync_source": str(source.id),
        "calsync_uid": "skate-1",
    }
    assert (skate["summary"], skate["location"]) == ("Public Skate", "Main rink")
    assert skate["start"] == {"dateTime": "2026-12-02T12:00:00+00:00", "timeZone": "UTC"}
    assert {row.calendar_id for row in mapped(db, source).values()} == {TARGET}


async def test_a_second_identical_sync_makes_no_google_calls(
    db, source, registry, connection, calendar
):
    await sync(db, source, registry, connection, SKATES)
    calendar.writes.clear()
    calendar.reads.clear()

    result = await sync(db, source, registry, connection, SKATES, now=NOW + timedelta(hours=1))

    assert result.status == "ok"
    assert calendar.writes == []
    assert calendar.reads == []


async def test_changed_event_is_patched_in_place(db, source, registry, connection, calendar):
    await sync(db, source, registry, connection, SKATES)
    google_id = mapped(db, source)["skate-1"].google_event_id
    calendar.writes.clear()

    moved = scraped("skate-1", "Public Skate", 1, location="Studio rink")
    await sync(db, source, registry, connection, [moved, *SKATES[1:]])

    assert calendar.writes == [("PATCH", TARGET, google_id)]
    assert calendar.events[TARGET][google_id]["location"] == "Studio rink"
    assert mapped(db, source)["skate-1"].content_hash == content_hash(moved)


async def test_future_events_gone_or_filtered_out_are_deleted(
    db, source, registry, connection, calendar
):
    await sync(db, source, registry, connection, SKATES)
    gone_id = mapped(db, source)["skate-2"].google_event_id
    source.include_kw = ["hockey"]
    db.commit()

    await sync(db, source, registry, connection, [SKATES[0], SKATES[2]])

    assert set(calendar.tagged(TARGET)) == {"hockey-1"}
    assert gone_id not in calendar.events[TARGET]
    assert set(mapped(db, source)) == {"hockey-1"}


async def test_past_events_are_never_deleted(db, source, registry, connection, calendar):
    await sync(db, source, registry, connection, SKATES)
    later = NOW + timedelta(days=4)

    await sync(db, source, registry, connection, [scraped("late", "Public Skate", 10)], later)

    assert {"skate-1", "skate-2", "late"} <= set(calendar.tagged(TARGET))
    assert not [write for write in calendar.writes if write[0] == "DELETE"]
    assert set(mapped(db, source)) == {"late"}


async def test_untagged_and_foreign_events_are_never_touched(
    db, source, registry, connection, calendar
):
    own = calendar.add_event(TARGET, summary="Dentist")
    foreign = calendar.add_event(
        TARGET,
        summary="Other source",
        extendedProperties={"private": {"calsync_source": "999", "calsync_uid": "skate-2"}},
    )
    await sync(db, source, registry, connection, SKATES)
    _point_map_at(db, source, "skate-1", own)
    _point_map_at(db, source, "skate-2", foreign)

    moved = scraped("skate-1", "Public Skate", 1, location="Studio rink")
    await sync(db, source, registry, connection, [moved, SKATES[2]])

    assert calendar.events[TARGET][own] == {"id": own, "summary": "Dentist"}
    assert calendar.events[TARGET][foreign]["summary"] == "Other source"
    touched = {event_id for method, _, event_id in calendar.writes if method != "POST"}
    assert touched.isdisjoint({own, foreign})


def _point_map_at(db, source, uid, google_event_id):
    """Corrupts a map row, as a bug or a hand edit might, to prove the tag check holds."""
    mapped(db, source)[uid].google_event_id = google_event_id
    db.commit()


async def test_event_deleted_in_google_is_inserted_again_on_change(
    db, source, registry, connection, calendar
):
    await sync(db, source, registry, connection, SKATES)
    calendar.events[TARGET].pop(mapped(db, source)["skate-1"].google_event_id)

    moved = scraped("skate-1", "Public Skate", 1, location="Studio rink")
    await sync(db, source, registry, connection, [moved, *SKATES[1:]])

    assert calendar.tagged(TARGET)["skate-1"]["location"] == "Studio rink"


@pytest.mark.parametrize(
    "runner_kwargs",
    [{"error": PageLimitExceeded("run exceeded 20 requests")}, {}],
    ids=["limit-hit", "empty-run"],
)
async def test_failed_scrape_makes_no_google_calls(
    db, source, registry, connection, calendar, runner_kwargs
):
    await sync(db, source, registry, connection, SKATES)
    calendar.writes.clear()

    result = await sync(db, source, registry, connection, [], **runner_kwargs)

    assert result.status == "error"
    assert calendar.writes == []
    assert set(calendar.tagged(TARGET)) == {"skate-1", "skate-2"}


async def test_changing_the_target_moves_future_events(db, source, registry, connection, calendar):
    await sync(db, source, registry, connection, SKATES)
    source.target_calendar_id = OTHER
    db.commit()

    await sync(db, source, registry, connection, SKATES)

    assert calendar.tagged(TARGET) == {}
    assert set(calendar.tagged(OTHER)) == {"skate-1", "skate-2"}
    assert {row.calendar_id for row in mapped(db, source).values()} == {OTHER}


async def test_clearing_the_target_removes_future_events(
    db, source, registry, connection, calendar
):
    await sync(db, source, registry, connection, SKATES)
    source.target_calendar_id = None
    db.commit()

    await sync(db, source, registry, connection, SKATES)
    calendar.writes.clear()
    await sync(db, source, registry, connection, SKATES)

    assert calendar.tagged(TARGET) == {}
    assert mapped(db, source) == {}
    assert calendar.writes == []


async def test_each_google_write_is_committed_before_the_next(
    db, sessions, source, registry, connection, calendar, monkeypatch
):
    """Another session can write while Google is being called, so the push holds no lock."""
    seen = []

    async def insert_and_peek(self, calendar_id, body):
        with sessions.begin() as other:
            other.get(Source, source.id).name = "Renamed mid-push"
        seen.append(body["extendedProperties"]["private"]["calsync_uid"])
        return f"evt-{len(seen)}"

    monkeypatch.setattr(
        "app.services.google_calendar.client.GoogleCalendarClient.insert_event", insert_and_peek
    )
    result = await sync(db, source, registry, connection, SKATES)

    assert result.status == "ok", result.error
    assert seen == ["skate-1", "skate-2"]


async def test_targets_run_after_the_stored_events_are_committed(db, sessions, source, registry):
    """The run's own transaction is closed, not just its savepoint released."""

    class Peek:
        async def apply(self, db, source, matched, now):
            self.open = db.in_transaction()
            with sessions() as other:
                self.visible = len(other.scalars(select(Event)).all())

    peek = Peek()
    runner = FakeRunner(SKATES)
    await run_source(db, source, registry=registry, runner=runner, targets=[peek], now=NOW)

    assert (peek.open, peek.visible) == (False, 3)


async def test_rate_limits_and_server_errors_are_retried(
    db, source, registry, connection, calendar
):
    calendar.failures = [(429, {"Retry-After": "2"}), (503, {})]

    result = await sync(db, source, registry, connection, SKATES)

    assert result.status == "ok", result.error
    assert set(calendar.tagged(TARGET)) == {"skate-1", "skate-2"}


async def test_errors_that_outlast_the_retries_fail_the_run(
    db, source, registry, connection, calendar
):
    calendar.failures = [(500, {})] * 10

    result = await sync(db, source, registry, connection, SKATES)

    assert result.status == "error"
    assert "Google Calendar answered 500" in result.error
    assert source.consecutive_failures == 1
    assert len(source.last_error) > 0


async def test_revoked_grant_asks_for_reconnect_and_clears_the_token(
    db, source, registry, connection, calendar
):
    calendar.grant_revoked = True

    result = await sync(db, source, registry, connection, SKATES)

    assert result.status == "error"
    assert "reconnect Google" in result.error
    assert db.get(User, source.user_id).refresh_token_enc is None
    assert calendar.writes == []


async def test_access_token_is_reused_across_runs(db, source, registry, connection, calendar):
    await sync(db, source, registry, connection, SKATES)
    await sync(db, source, registry, connection, [*SKATES, scraped("skate-3", "Public Skate", 4)])

    assert calendar.refreshes == 1


async def test_source_without_target_or_history_has_no_google_target(db, source, connection):
    source.target_calendar_id = None
    db.commit()
    assert google_targets(connection)(db, source) == []
