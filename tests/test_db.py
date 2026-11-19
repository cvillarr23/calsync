from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from app.db import (
    SCHEMA_VERSION,
    Event,
    SchemaVersion,
    Source,
    User,
    init_db,
    make_engine,
)


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "data")
    yield init_db(engine)
    engine.dispose()


def test_creates_database_in_data_dir(tmp_path, sessions):
    assert (tmp_path / "data" / "calsync.db").is_file()


def test_init_is_idempotent_and_versioned(tmp_path, sessions):
    init_db(make_engine(tmp_path / "data"))
    with sessions() as db:
        assert db.scalars(select(SchemaVersion.version)).all() == [SCHEMA_VERSION]


def test_source_defaults(sessions):
    with sessions.begin() as db:
        user = User(email="a@example.com")
        db.add(user)
        db.flush()
        first = Source(user_id=user.id, name="a", adapter_id="x")
        second = Source(user_id=user.id, name="b", adapter_id="x")
        db.add_all([first, second])
        db.flush()
        assert (first.interval_min, first.lookahead_days, first.enabled) == (360, 60, True)
        assert first.include_kw == [] and first.exclude_kw == []
        assert len(first.feed_token) >= 32
        assert first.feed_token != second.feed_token


def test_datetimes_round_trip_as_aware_utc(sessions):
    start = datetime(2026, 12, 1, 18, 30, tzinfo=UTC)
    with sessions.begin() as db:
        source = _source(db)
        db.add(_event(source, start))
    with sessions() as db:
        assert db.scalar(select(Event.start_utc)) == start


def test_naive_datetimes_are_rejected(sessions):
    with pytest.raises(StatementError, match="timezone-aware"), sessions.begin() as db:
        db.add(_event(_source(db), datetime(2026, 12, 1)))


def test_foreign_keys_are_enforced(sessions):
    with pytest.raises(IntegrityError), sessions.begin() as db:
        db.add(Source(user_id=999, name="orphan", adapter_id="x"))


def _source(db) -> Source:
    user = User(email="a@example.com")
    db.add(user)
    db.flush()
    source = Source(user_id=user.id, name="s", adapter_id="x")
    db.add(source)
    db.flush()
    return source


def _event(source: Source, start: datetime) -> Event:
    return Event(
        source_id=source.id,
        uid="u1",
        title="t",
        start_utc=start,
        content_hash="h",
        last_seen_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def test_request_session_commits_before_response():
    """A request-scoped session would commit after the response, so a client
    could read stale data right after a 201."""
    from typing import get_args

    from app.db import Db

    assert get_args(Db)[1].scope == "function"
