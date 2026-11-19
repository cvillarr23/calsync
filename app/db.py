"""SQLite storage: models, engine and schema versioning.

The schema is created with `create_all` and versioned in `schema_version`.
Later changes go in `MIGRATIONS` as ordered steps; `init_db` runs the ones a
database hasn't seen yet.
"""

import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_FILENAME = "calsync.db"


class UtcDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite and hands back aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_feed_token() -> str:
    return secrets.token_urlsafe(24)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)


class AdapterDef(Base):
    """A user-created adapter definition, stored as the YAML the user wrote."""

    __tablename__ = "adapter_defs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    yaml: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    adapter_id: Mapped[str] = mapped_column(String, index=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    include_kw: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_kw: Mapped[list[str]] = mapped_column(JSON, default=list)
    interval_min: Mapped[int] = mapped_column(Integer, default=360)
    lookahead_days: Mapped[int] = mapped_column(Integer, default=60)
    target_calendar_id: Mapped[str | None] = mapped_column(String)
    feed_token: Mapped[str] = mapped_column(String, unique=True, default=new_feed_token)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_status: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    """The latest copy of each event an adapter produced for a source, filtered or not."""

    __tablename__ = "events"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    start_utc: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    end_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)


class GoogleMap(Base):
    """Which Google Calendar event mirrors each calsync event, and the hash it was synced at."""

    __tablename__ = "google_map"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    google_event_id: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)


SCHEMA_VERSION = 1
Migration = Callable[[Session], None]
MIGRATIONS: dict[int, Migration] = {}
"""Steps that bring a database from version n-1 to n, keyed by n. Version 1 is `create_all`."""


def make_engine(data_dir: Path) -> Engine:
    """An engine for `<data_dir>/calsync.db`, with foreign keys enforced and WAL journaling."""
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / DB_FILENAME}")
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db(engine: Engine) -> sessionmaker[Session]:
    """Create or upgrade the schema, then return a session factory."""
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        _migrate(session)
    return factory


def _migrate(session: Session) -> None:
    current = session.scalar(select(SchemaVersion.version)) or 0
    if current == 0:
        session.add(SchemaVersion(version=SCHEMA_VERSION))
        return
    for version in range(current + 1, SCHEMA_VERSION + 1):
        MIGRATIONS[version](session)
    session.get_one(SchemaVersion, current).version = SCHEMA_VERSION


def get_db(request: Request) -> Iterator[Session]:
    """One session per request, committed when the handler succeeds."""
    with request.app.state.sessions.begin() as session:
        yield session


Db = Annotated[Session, Depends(get_db, scope="function")]
"""A request's session. Function scope commits before the response is sent, so a
client that gets a 201 can read its write back on the next request."""
