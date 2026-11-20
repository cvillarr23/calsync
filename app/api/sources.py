"""`/api/sources`: the user's calendar sources, and Sync now."""

from fastapi import APIRouter, BackgroundTasks, Response, status

from app.api.deps import AppScheduler, AppSettings, CurrentUser, Registry
from app.db.models import Source
from app.db.session import Db
from app.mappers.source import source_columns, source_out
from app.mappers.sync_run import sync_run_out
from app.schemas.source import SourceCreate, SourceOut, SourcePatch
from app.schemas.sync_run import SyncRunOut
from app.services import sources
from app.services.errors import Conflict, NotFound
from app.services.scheduling import SyncInProgress, SyncScheduler
from app.settings import Settings

router = APIRouter(prefix="/sources")


@router.get("")
def list_sources(
    db: Db, user: CurrentUser, settings: AppSettings, scheduler: AppScheduler
) -> list[SourceOut]:
    return [_out(settings, scheduler, row) for row in sources.user_sources(db, user)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceCreate,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
    tasks: BackgroundTasks,
) -> SourceOut:
    columns = source_columns(body, set(SourcePatch.model_fields))
    source = sources.create_source(db, user, columns, registry, settings)
    return _scheduled_out(settings, scheduler, tasks, source)


@router.get("/{source_id}")
def get_source(
    source_id: int, db: Db, user: CurrentUser, settings: AppSettings, scheduler: AppScheduler
) -> SourceOut:
    return _out(settings, scheduler, sources.owned_source(db, user, source_id))


@router.patch("/{source_id}")
def update_source(
    source_id: int,
    body: SourcePatch,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
    tasks: BackgroundTasks,
) -> SourceOut:
    source = sources.owned_source(db, user, source_id)
    sources.update_source(source, source_columns(body, body.model_fields_set), registry, settings)
    db.flush()
    return _scheduled_out(settings, scheduler, tasks, source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int, db: Db, user: CurrentUser, scheduler: AppScheduler, tasks: BackgroundTasks
) -> Response:
    db.delete(sources.owned_source(db, user, source_id))
    tasks.add_task(scheduler.source_deleted, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/sync")
async def sync_source(
    source_id: int, db: Db, user: CurrentUser, scheduler: AppScheduler
) -> SyncRunOut:
    """Sync now. Returns 409 while the source is already syncing, rather than queueing."""
    sources.owned_source(db, user, source_id)
    db.commit()  # end this request's transaction, so it can't block the run's writes
    try:
        result = await scheduler.sync_now(source_id)
    except SyncInProgress as err:
        raise Conflict("a sync of this source is already running") from err
    if result is None:
        raise NotFound(f"source {source_id} not found")
    return sync_run_out(result)


def _out(settings: Settings, scheduler: SyncScheduler, source: Source) -> SourceOut:
    return source_out(settings, source, scheduler.shown_run_at(source))


def _scheduled_out(
    settings: Settings, scheduler: SyncScheduler, tasks: BackgroundTasks, source: Source
) -> SourceOut:
    """Reschedule after the request commits, so a due job can't run before the source exists.

    The run time is fixed here, so the response and the job agree.
    """
    run_at = scheduler.planned_run_at(source)
    tasks.add_task(scheduler.schedule, source.id, run_at)
    return source_out(settings, source, run_at)
