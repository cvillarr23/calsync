from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import parse_definition
from app.db.engine import init_db, make_engine
from app.db.models import Event, Source, User
from app.services.sync import content_hash, matched_events, run_source
from tests.adapters.conftest import HTML_DEF
from tests.support import FakeRunner, RecordingTarget

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)


def scraped(uid, title, days, hours=1.5, **extra):
    start = NOW + timedelta(days=days)
    return ScrapedEvent(uid, title, start, start + timedelta(hours=hours), **extra)


FIXTURE = [
    scraped("skate-1", "Public Skate", 1, location="Main rink"),
    scraped("theme-1", "Public Skate Theme Night: EDM/House", 2),
    scraped("hockey-1", "Drop-in Hockey", 3),
    scraped("skate-1", "Public Skate", 1, location="Main rink"),  # repeated by an overlapping page
]


@pytest.fixture
def registry():
    definition = dict(
        HTML_DEF, params={"url": {"type": "url"}, "days": {"type": "int", "default": 7}}
    )
    registry = AdapterRegistry()
    registry.add_source(lambda user_id: [parse_definition(definition)])
    return registry


@pytest.fixture
def db(tmp_path):
    engine = make_engine(tmp_path / "data")
    with init_db(engine)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def source(db):
    user = User(email="a@example.com")
    db.add(user)
    db.flush()
    source = Source(
        user_id=user.id,
        name="Rink",
        adapter_id="rec-center",
        params_json={"url": "https://rink.example/schedule"},
        include_kw=["public skate"],
        exclude_kw=["theme night"],
        lookahead_days=14,
    )
    db.add(source)
    db.commit()
    return source


async def sync(db, source, registry, runner, now=NOW, **kwargs):
    result = await run_source(db, source, registry=registry, runner=runner, now=now, **kwargs)
    db.commit()
    return result


def stored(db, source):
    rows = db.scalars(select(Event).where(Event.source_id == source.id).order_by(Event.uid))
    return {row.uid: row for row in rows}


async def test_two_runs_give_no_duplicates_and_stable_hashes(db, source, registry):
    runner = FakeRunner(FIXTURE)
    first = await sync(db, source, registry, runner)
    hashes = {uid: row.content_hash for uid, row in stored(db, source).items()}
    second = await sync(db, source, registry, runner, now=NOW + timedelta(minutes=30))

    assert (first.fetched, first.inserted, first.matched) == (4, 3, 1)
    assert (second.inserted, second.updated, second.unchanged, second.removed) == (0, 0, 3, 0)
    assert db.scalar(select(func.count()).select_from(Event)) == 3
    assert {uid: row.content_hash for uid, row in stored(db, source).items()} == hashes


async def test_run_passes_window_and_params_with_defaults(db, source, registry):
    runner = FakeRunner(FIXTURE)
    await sync(db, source, registry, runner)
    assert runner.calls == [
        (
            "rec-center",
            {"days": 7, "url": "https://rink.example/schedule"},
            NOW,
            NOW + timedelta(days=14),
        )
    ]


async def test_changed_event_is_updated_with_new_hash(db, source, registry):
    await sync(db, source, registry, FakeRunner(FIXTURE))
    before = stored(db, source)["skate-1"].content_hash
    moved = scraped("skate-1", "Public Skate", 1, location="Studio rink")
    result = await sync(db, source, registry, FakeRunner([moved, *FIXTURE[1:3]]))

    row = stored(db, source)["skate-1"]
    assert result.updated == 1
    assert row.location == "Studio rink"
    assert row.content_hash == content_hash(moved) != before


async def test_future_events_gone_from_site_are_removed_but_past_kept(db, source, registry):
    started = scraped("early", "Public Skate", 0.5)
    await sync(db, source, registry, FakeRunner([started, *FIXTURE]))
    later = NOW + timedelta(days=1, hours=12)
    result = await sync(db, source, registry, FakeRunner([started]), now=later)

    assert result.removed == 2  # theme-1 and hockey-1 are still in the future
    assert set(stored(db, source)) == {"early", "skate-1"}


async def test_empty_run_fails_instead_of_removing_future_events(db, source, registry):
    await sync(db, source, registry, FakeRunner(FIXTURE))
    result = await sync(db, source, registry, FakeRunner([]))

    assert result.status == "error"
    assert "returned no events" in result.error
    assert len(stored(db, source)) == 3


async def test_empty_run_is_fine_when_nothing_future_is_stored(db, source, registry):
    result = await sync(db, source, registry, FakeRunner([]))
    assert (result.status, result.fetched) == ("ok", 0)


async def test_matched_events_filters_and_skips_ended(db, source, registry):
    past = scraped("past", "Public Skate", -2)
    await sync(db, source, registry, FakeRunner([past, *FIXTURE]))
    assert [e.uid for e in matched_events(db, source, NOW)] == ["skate-1"]


async def test_success_records_status(db, source, registry):
    source.consecutive_failures = 3
    result = await sync(db, source, registry, FakeRunner(FIXTURE))
    assert result.status == "ok"
    assert (source.last_status, source.last_error, source.last_run_at) == ("ok", None, NOW)
    assert source.consecutive_failures == 0


async def test_adapter_failure_is_recorded_and_events_kept(db, source, registry):
    await sync(db, source, registry, FakeRunner(FIXTURE))
    later = NOW + timedelta(hours=1)
    first = await sync(db, source, registry, FakeRunner(error=AdapterRunError("site down")), later)
    await sync(db, source, registry, FakeRunner(error=RuntimeError("boom")), later)

    assert (first.status, first.error) == ("error", "site down")
    assert (source.last_status, source.last_error) == ("error", "boom")
    assert source.consecutive_failures == 2
    assert len(stored(db, source)) == 3


async def test_unknown_adapter_is_recorded(db, source, registry):
    source.adapter_id = "gone"
    result = await sync(db, source, registry, FakeRunner(FIXTURE))
    assert result.status == "error"
    assert "'gone' not found" in source.last_error


async def test_bad_event_rolls_back_the_whole_run(db, source, registry):
    naive = ScrapedEvent("naive", "Public Skate", datetime(2026, 12, 5, 9))
    result = await sync(db, source, registry, FakeRunner([*FIXTURE, naive]))
    assert result.status == "error"
    assert "without a time zone" in result.error
    assert stored(db, source) == {}


async def test_targets_get_matched_events(db, source, registry):
    target = RecordingTarget()
    await sync(db, source, registry, FakeRunner(FIXTURE), targets=[target])
    assert target.calls == [["skate-1"]]


async def test_target_failure_is_recorded_after_events_are_stored(db, source, registry):
    target = RecordingTarget(error=RuntimeError("calendar API said no"))
    result = await sync(db, source, registry, FakeRunner(FIXTURE), targets=[target])
    assert result.error == "calendar API said no"
    assert source.last_status == "error"
    assert len(stored(db, source)) == 3


def test_content_hash_covers_every_shown_field():
    base = scraped("x", "Public Skate", 1)
    variants = [
        scraped("x", "Public skate", 1),
        scraped("x", "Public Skate", 2),
        scraped("x", "Public Skate", 1, hours=2),
        scraped("x", "Public Skate", 1, location="Rink"),
        scraped("x", "Public Skate", 1, description="Bring skates"),
        scraped("x", "Public Skate", 1, url="https://rink.example/e/1"),
    ]
    assert content_hash(base) == content_hash(scraped("x", "Public Skate", 1))
    assert content_hash(base) not in {content_hash(v) for v in variants}
