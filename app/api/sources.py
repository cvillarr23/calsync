"""`/api/sources`: the user's calendar sources, and Sync now."""

from fastapi import APIRouter, BackgroundTasks, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.api.deps import AppScheduler, AppSettings, CurrentUser, Registry
from app.api.errors import conflict, not_found, unprocessable
from app.db.models import Source, User
from app.db.session import Db
from app.mappers.source import source_columns, source_out
from app.mappers.sync_run import sync_run_out
from app.schemas.source import SourceCreate, SourceOut, SourcePatch
from app.schemas.sync_run import SyncRunOut
from app.services.scheduling import SyncInProgress, SyncScheduler
from app.services.source_validation import source_problems
from app.settings import Settings

router = APIRouter(prefix="/sources")


@router.get("")
def list_sources(
    db: Db, user: CurrentUser, settings: AppSettings, scheduler: AppScheduler
) -> list[SourceOut]:
    rows = db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.id))
    return [_out(settings, scheduler, row) for row in rows]


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
    source = Source(user_id=user.id)
    _apply(source, body, set(SourcePatch.model_fields), registry, settings)
    db.add(source)
    db.flush()
    return _scheduled_out(settings, scheduler, tasks, source)


@router.get("/{source_id}")
def get_source(
    source_id: int, db: Db, user: CurrentUser, settings: AppSettings, scheduler: AppScheduler
) -> SourceOut:
    return _out(settings, scheduler, _owned_source(db, user, source_id))


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
    source = _owned_source(db, user, source_id)
    _apply(source, body, body.model_fields_set, registry, settings)
    db.flush()
    return _scheduled_out(settings, scheduler, tasks, source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int, db: Db, user: CurrentUser, scheduler: AppScheduler, tasks: BackgroundTasks
) -> Response:
    db.delete(_owned_source(db, user, source_id))
    tasks.add_task(scheduler.source_deleted, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/sync")
async def sync_source(
    source_id: int, db: Db, user: CurrentUser, scheduler: AppScheduler
) -> SyncRunOut:
    """Sync now. Returns 409 while the source is already syncing, rather than queueing."""
    _owned_source(db, user, source_id)
    db.commit()  # end this request's transaction, so it can't block the run's writes
    try:
        result = await scheduler.sync_now(source_id)
    except SyncInProgress as err:
        raise conflict("a sync of this source is already running") from err
    if result is None:
        raise not_found(f"source {source_id} not found")
    return sync_run_out(result)


def _owned_source(db: Session, user: User, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.user_id != user.id:
        raise not_found(f"source {source_id} not found")
    return source


def _out(settings: Settings, scheduler: SyncScheduler, source: Source) -> SourceOut:
    """The job's fire time; the planned one while a run has the job off the schedule."""
    run_at = scheduler.next_run_at(source.id) or scheduler.planned_run_at(source)
    return source_out(settings, source, run_at)


def _scheduled_out(
    settings: Settings, scheduler: SyncScheduler, tasks: BackgroundTasks, source: Source
) -> SourceOut:
    """Reschedule after the request commits, so a due job can't run before the source exists.

    The run time is fixed here, so the response and the job agree.
    """
    run_at = scheduler.planned_run_at(source)
    tasks.add_task(scheduler.schedule, source.id, run_at)
    return source_out(settings, source, run_at)


def _apply(
    source: Source,
    body: SourcePatch,
    fields: set[str],
    registry: AdapterRegistry,
    settings: Settings,
) -> None:
    """Write the given fields, then validate the source as a whole.

    A rejected change raises before the request's session commits, so nothing is saved.
    """
    for column, value in source_columns(body, fields).items():
        setattr(source, column, value)
    problems = source_problems(source, registry, settings)
    if problems:
        raise unprocessable(problems)
