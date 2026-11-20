import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.events import AdapterRunner, default_runner
from app.adapters.registry import AdapterRegistry
from app.db.models import Source
from app.services.sync import SyncResult, run_source

log = logging.getLogger(__name__)


class SyncInProgress(RuntimeError):
    """The source is already syncing; a second run would insert the same events twice."""


class SourceRuns:
    """Runs one source's sync at a time, each in its own session.

    Sync now and the schedule share this, so the two never overlap on one source.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        registry: AdapterRegistry,
        runner: AdapterRunner = default_runner,
    ) -> None:
        self.runner = runner
        self.closing = False
        self._sessions = sessions
        self._registry = registry
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, source_id: int) -> asyncio.Lock:
        return self._locks[source_id]

    def running(self, source_id: int) -> bool:
        return self.lock(source_id).locked()

    async def run(self, source_id: int, *, now: datetime, scheduled: bool) -> SyncResult | None:
        """Sync the source, or return None when there is nothing to run.

        Raises `SyncInProgress` instead of waiting: the run already going will finish the job.
        """
        if self.running(source_id):
            raise SyncInProgress(f"source {source_id} is already syncing")
        async with self.lock(source_id):
            return await self._run_locked(source_id, now, scheduled)

    async def drain(self, timeout: float) -> None:
        """Refuse new runs, then wait up to `timeout` seconds for the ones in flight."""
        self.closing = True
        try:
            await asyncio.wait_for(self._all_idle(), timeout)
        except TimeoutError:
            log.warning("syncs still running after %ss; stopping them", timeout)

    async def _run_locked(
        self, source_id: int, now: datetime, scheduled: bool
    ) -> SyncResult | None:
        with self._sessions.begin() as db:
            source = db.get(Source, source_id)
            if not self._should_run(source, scheduled):
                return None
            return await run_source(
                db, source, registry=self._registry, runner=self.runner, now=now
            )

    def _should_run(self, source: Source | None, scheduled: bool) -> bool:
        """Deleted sources never run; disabled ones only run when asked to by hand."""
        if self.closing or source is None:
            return False
        return source.enabled or not scheduled

    async def _all_idle(self) -> None:
        for lock in list(self._locks.values()):
            async with lock:
                pass
