"""Opening the database file and bringing its schema up to date."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base
from app.db.migrations import migrate

DB_FILENAME = "calsync.db"


def make_engine(data_dir: Path) -> Engine:
    """An engine for `<data_dir>/calsync.db`, with foreign keys enforced and WAL journaling."""
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / DB_FILENAME}")
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def init_db(engine: Engine) -> sessionmaker[Session]:
    """Create or upgrade the schema, then return a session factory."""
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        migrate(session)
    return factory


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
