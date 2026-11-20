from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anyio
import pytest

from app.adapters.events import AdapterRunError
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import parse_definition
from app.db.base import utcnow
from app.db.engine import init_db, make_engine
from app.db.models import Source, User
from app.services.scheduling import SourceRuns, SyncInProgress, SyncScheduler
from tests.adapters.conftest import HTML_DEF
from tests.support import FakeRunner, GatedRunner

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)
SETTINGS = SimpleNamespace(min_interval_min=30, fetch_timeout_s=5.0)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(tmp_path / "data")
    yield init_db(engine)
    engine.dispose()


@pytest.fixture
def registry():
    registry = AdapterRegistry()
    registry.add_source(lambda: [parse_definition(HTML_DEF)])
    return registry


def add_source(sessions, **columns):
    with sessions.begin() as db:
        user = User(email="a@example.com")
        db.add(user)
        db.flush()
        source = Source(
            user_id=user.id,
            name="Rink",
            adapter_id="rec-center",
            params_json={"url": "https://rink.example/schedule"},
            interval_min=60,
            **columns,
        )
        db.add(source)
    return source


def update_source(sessions, source, **columns):
    with sessions.begin() as db:
        row = db.get(Source, source.id)
        for name, value in columns.items():
            setattr(row, name, value)
    return row


@pytest.fixture
async def make_scheduler(sessions, registry):
    """Build a scheduler on this test's loop; it is shut down when the test ends."""
    started = []

    def make(runner=None, clock=None, paused=True):
        runs = SourceRuns(sessions, registry, runner or FakeRunner())
        scheduler = SyncScheduler(runs, sessions, SETTINGS, clock=clock or Clock(NOW))
        scheduler.start(paused=paused)
        started.append(scheduler)
        return scheduler

    yield make
    for scheduler in started:
        await scheduler.shutdown()


async def test_changing_the_interval_moves_the_job(sessions, make_scheduler):
    source = add_source(sessions, last_run_at=NOW - timedelta(minutes=10))
    scheduler = make_scheduler()
    scheduler.schedule_all()
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=50)

    scheduler.source_changed(update_source(sessions, source, interval_min=120))
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=110)


async def test_disabled_and_deleted_sources_have_no_job(sessions, make_scheduler):
    source = add_source(sessions, enabled=False)
    scheduler = make_scheduler()
    scheduler.schedule_all()
    assert scheduler.next_run_at(source.id) is None

    scheduler.source_changed(update_source(sessions, source, enabled=True))
    assert scheduler.next_run_at(source.id) == NOW
    scheduler.source_deleted(source.id)
    assert scheduler.next_run_at(source.id) is None


async def test_failures_back_off_and_a_success_resets(sessions, make_scheduler):
    source = add_source(sessions)
    runner = FakeRunner(error=AdapterRunError("site down"))
    scheduler = make_scheduler(runner)

    assert (await scheduler.sync_now(source.id)).status == "error"
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=120)
    await scheduler.sync_now(source.id)
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=240)

    runner.error = None
    assert (await scheduler.sync_now(source.id)).status == "ok"
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=60)


async def test_sync_now_during_a_run_does_not_start_another(sessions, make_scheduler):
    source = add_source(sessions)
    runner = GatedRunner()
    scheduler = make_scheduler(runner)

    async with anyio.create_task_group() as tg:
        tg.start_soon(scheduler.sync_now, source.id)
        await runner.started.wait()
        with pytest.raises(SyncInProgress):
            await scheduler.sync_now(source.id)
        await scheduler._run_scheduled(source.id)  # a scheduled run is skipped quietly
        runner.release.set()

    assert len(runner.calls) == 1
    assert scheduler.next_run_at(source.id) == NOW + timedelta(minutes=60)


async def test_a_due_job_runs_and_reschedules_itself(sessions, make_scheduler):
    source = add_source(sessions)
    runner = GatedRunner()
    now = utcnow()
    scheduler = make_scheduler(runner, clock=Clock(now), paused=False)
    scheduler.schedule_all()

    with anyio.fail_after(5):
        await runner.started.wait()
        runner.release.set()
        while scheduler.next_run_at(source.id) != now + timedelta(minutes=60):
            await anyio.sleep(0.01)
    assert len(runner.calls) == 1


async def test_disabled_sources_only_sync_by_hand(sessions, make_scheduler):
    source = add_source(sessions, enabled=False)
    runner = FakeRunner()
    scheduler = make_scheduler(runner)

    await scheduler._run_scheduled(source.id)
    assert runner.calls == []
    assert (await scheduler.sync_now(source.id)).status == "ok"
    assert len(runner.calls) == 1
    assert scheduler.next_run_at(source.id) is None


async def test_shutdown_waits_for_a_run_then_refuses_new_ones(sessions, make_scheduler):
    source = add_source(sessions)
    runner = GatedRunner()
    scheduler = make_scheduler(runner)
    results = []

    async def sync():
        results.append(await scheduler.sync_now(source.id))

    async with anyio.create_task_group() as tg:
        tg.start_soon(sync)
        await runner.started.wait()
        tg.start_soon(scheduler.runs.drain, 5.0)
        await anyio.sleep(0.05)
        assert results == []  # draining waits for the run in flight
        runner.release.set()

    assert results[0].status == "ok"
    assert await scheduler.sync_now(source.id) is None
    assert len(runner.calls) == 1
