"""Schema versioning.

Version 1 is whatever `create_all` builds. Each later change adds a step to
`MIGRATIONS` and bumps `SCHEMA_VERSION`; `migrate` runs the steps a database
hasn't seen yet.
"""

from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models.schema_version import SchemaVersion

SCHEMA_VERSION = 2
Migration = Callable[[Session], None]


def _google_map_target_columns(session: Session) -> None:
    """Version 2: `google_map` remembers each pushed event's calendar and start time."""
    session.execute(text("ALTER TABLE google_map ADD COLUMN calendar_id VARCHAR"))
    session.execute(text("ALTER TABLE google_map ADD COLUMN start_utc DATETIME"))


MIGRATIONS: dict[int, Migration] = {2: _google_map_target_columns}
"""Steps that bring a database from version n-1 to n, keyed by n."""


def migrate(session: Session) -> None:
    current = session.scalar(select(SchemaVersion.version)) or 0
    if current == 0:
        session.add(SchemaVersion(version=SCHEMA_VERSION))
        return
    for version in range(current + 1, SCHEMA_VERSION + 1):
        MIGRATIONS[version](session)
    session.get_one(SchemaVersion, current).version = SCHEMA_VERSION
