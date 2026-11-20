import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import utcnow
from app.db.models import Source
from app.services.scheduling.backoff import next_run_at
from app.services.scheduling.runs import SourceRuns, SyncInProgress
from app.services.sync import SyncResult
from app.settings import Settings

JOB_DEFAULTS = {"max_instances": 1, "coalesce": True, "misfire_grace_time": None}
"""One run per job at a time; runs missed while the app was busy or asleep collapse into
one, and a late run still runs rather than being dropped."""


def _job_id(source_id: int) -> str:
    return f"source-{source_id}"


class SyncScheduler:
    """One date-triggered job per enabled source, moved after every run.

    A date trigger rather than an interval one, because the delay to the next run
    changes with each failure. Each run reschedules its own job from the source's
    stored columns, so the schedule survives restarts.
    """

    def __init__(
        self,
        runs: SourceRuns,
        sessions: sessionmaker[Session],
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.runs = runs
        self._sessions = sessions
        self._min_interval = settings.min_interval_min
        self._drain_timeout = settings.fetch_timeout_s
        self._clock = clock
        self._aps = AsyncIOScheduler(timezone=UTC, job_defaults=JOB_DEFAULTS)

    def start(self, *, paused: bool = False) -> None:
        """Start on the running event loop; paused, jobs are kept but never fire."""
        self._aps.start(paused=paused)

    def schedule_all(self) -> None:
        with self._sessions() as db:
            for source in db.scalars(select(Source).where(Source.enabled)):
                self.source_changed(source)

    def source_changed(self, source: Source) -> None:
        """Move the source's job to its next run, or drop it if the source is disabled."""
        self.schedule(source.id, self.planned_run_at(source))

    def schedule(self, source_id: int, run_at: datetime | None) -> None:
        """Put the source's job at `run_at`; None drops the job."""
        if run_at is None:
            self.source_deleted(source_id)
            return
        self._aps.add_job(
            self._run_scheduled,
            "date",
            run_date=run_at,
            args=[source_id],
            id=_job_id(source_id),
            replace_existing=True,
        )

    def source_deleted(self, source_id: int) -> None:
        try:
            self._aps.remove_job(_job_id(source_id))
        except JobLookupError:
            pass

    def planned_run_at(self, source: Source) -> datetime | None:
        """When the source syncs next by schedule; None when it is disabled."""
        if not source.enabled:
            return None
        return next_run_at(source, self._clock(), self._min_interval)

    def next_run_at(self, source_id: int) -> datetime | None:
        """The fire time of the source's job, if it has one."""
        job = self._aps.get_job(_job_id(source_id))
        return job.next_run_time if job else None

    def shown_run_at(self, source: Source) -> datetime | None:
        """The job's fire time; the planned one while a run has the job off the schedule."""
        return self.next_run_at(source.id) or self.planned_run_at(source)

    async def sync_now(self, source_id: int) -> SyncResult | None:
        """Run the source now, enabled or not. Raises `SyncInProgress` if it is running."""
        return await self._run(source_id, scheduled=False)

    async def shutdown(self) -> None:
        """Stop firing jobs, let in-flight runs finish within the fetch time limit, then stop."""
        self._aps.pause()
        await self.runs.drain(self._drain_timeout)
        self._aps.shutdown(wait=False)
        await asyncio.sleep(0)  # the asyncio scheduler shuts down on the loop's next turn

    async def _run_scheduled(self, source_id: int) -> None:
        """A scheduled run that finds the source busy is skipped; the busy run reschedules."""
        try:
            await self._run(source_id, scheduled=True)
        except SyncInProgress:
            pass

    async def _run(self, source_id: int, *, scheduled: bool) -> SyncResult | None:
        """Run, then reschedule even if the run raised, so the source never drops off.

        The busy check comes first: rescheduling from a busy source's old columns would
        make the job due at once and spin.
        """
        if self.runs.running(source_id):
            raise SyncInProgress(f"source {source_id} is already syncing")
        try:
            return await self.runs.run(source_id, now=self._clock(), scheduled=scheduled)
        finally:
            self._reschedule(source_id)

    def _reschedule(self, source_id: int) -> None:
        """Reload the source, since its interval may have been edited during the run."""
        if self.runs.closing:
            return
        with self._sessions() as db:
            source = db.get(Source, source_id)
        if source is None:
            self.source_deleted(source_id)
        else:
            self.source_changed(source)
