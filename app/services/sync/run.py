from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.events import AdapterRunner, default_runner
from app.adapters.registry import AdapterRegistry
from app.db.base import utcnow
from app.db.models import Source
from app.services.sync.event_store import store_events
from app.services.sync.matching import matched_events
from app.services.sync.result import SyncResult
from app.services.sync.scrape import scrape
from app.services.sync.status import record_failure, record_success
from app.services.sync.target import SyncTarget


async def run_source(
    db: Session,
    source: Source,
    *,
    registry: AdapterRegistry,
    runner: AdapterRunner = default_runner,
    targets: Iterable[SyncTarget] = (),
    now: datetime | None = None,
) -> SyncResult:
    """Run one sync and record its outcome on the source. Failures are recorded, not raised."""
    now = now or utcnow()
    try:
        scraped = await scrape(source, registry, runner, now)
        with db.begin_nested():
            result = store_events(db, source, scraped, now)
        matched = matched_events(db, source, now)
        result.matched = len(matched)
        for target in targets:
            await target.apply(db, source, matched, now)
    except Exception as err:
        return record_failure(source, err, now)
    record_success(source, now)
    return result
