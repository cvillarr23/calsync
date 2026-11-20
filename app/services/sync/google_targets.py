from collections.abc import Callable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import GoogleMap, Source, User
from app.services.google_calendar import GoogleConnection
from app.services.sync.google_target import GoogleCalendarTarget
from app.services.sync.target import SyncTarget

TargetFactory = Callable[[Session, Source], list[SyncTarget]]


def no_targets(db: Session, source: Source) -> list[SyncTarget]:
    return []


def google_targets(connection: GoogleConnection) -> TargetFactory:
    """The Google push for a source with a target calendar, or with events left to clean up."""

    def targets(db: Session, source: Source) -> list[SyncTarget]:
        if source.target_calendar_id is None and not _has_mapped(db, source):
            return []
        user = db.get_one(User, source.user_id)
        return [GoogleCalendarTarget(lambda: connection.client(user))]

    return targets


def _has_mapped(db: Session, source: Source) -> bool:
    return bool(db.scalar(select(exists().where(GoogleMap.source_id == source.id))))
