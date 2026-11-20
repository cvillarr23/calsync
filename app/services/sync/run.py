from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.events import AdapterRunner, default_runner
from app.adapters.registry import AdapterRegistry
from app.db.base import utcnow
from app.db.models import Source
from app.services.google_calendar import GoogleReconnectNeeded
from app.services.sync.event_store import store_events
from app.services.sync.matching import matched_events
from app.services.sync.result import SyncResult
from app.services.sync.scrape import scrape
from app.services.sync.status import record_failure, record_success
from app.services.sync.target import SyncTarget
from app.services.users import forget_google_grant


async def run_source(
    db: Session,
    source: Source,
    *,
    registry: AdapterRegistry,
    runner: AdapterRunner = default_runner,
    targets: Iterable[SyncTarget] = (),
    now: datetime | None = None,
) -> SyncResult:
    """Run one sync and record its outcome on the source. Failures are recorded, not raised.

    Stored events are committed before the targets run, so a slow or failing push
    neither holds the database lock nor rolls the stored events back.
    """
    now = now or utcnow()
    try:
        scraped = await scrape(source, registry, runner, now)
        with db.begin_nested():
            result = store_events(db, source, scraped, now)
        matched = matched_events(db, source, now)
        result.matched = len(matched)
        db.commit()
        for target in targets:
            await target.apply(db, source, matched, now)
    except Exception as err:
        return _failed(db, source, err, now)
    record_success(source, now)
    return result


def _failed(db: Session, source: Source, err: Exception, now: datetime) -> SyncResult:
    """A lost Google grant is cleared, so the next sign-in asks Google for a new one."""
    db.rollback()
    if isinstance(err, GoogleReconnectNeeded):
        forget_google_grant(db, source.user_id)
    return record_failure(source, err, now)
