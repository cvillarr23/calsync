"""The sources pages: the list, the form with its live preview, and Sync now."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.adapters.schema import error_list
from app.api.deps import AppScheduler, AppSettings, CurrentUser, Registry
from app.db.base import utcnow
from app.db.models import Source, User
from app.db.models.source import DEFAULT_LOOKAHEAD_DAYS
from app.db.session import Db
from app.mappers.pages import source_row
from app.mappers.source import source_columns
from app.mappers.source_form import (
    PARAM_PREFIX,
    blank_form_values,
    echo_form_values,
    source_form_data,
    source_form_values,
)
from app.schemas.pages import SourceRow
from app.schemas.source import SourceCreate, SourcePatch
from app.services import sources
from app.services.adapter_suggest import suggest_adapters
from app.services.errors import Invalid
from app.services.preview import preview_source
from app.services.scheduling import SyncInProgress, SyncScheduler
from app.services.source_validation import source_problems
from app.services.sync import matched_events
from app.settings import Settings
from app.web.rendering import render

router = APIRouter()

FORM_FIELDS = set(SourcePatch.model_fields) - {"target_calendar_id"}
"""The form doesn't offer calendar targets yet, so saving it leaves the target alone."""


@router.get("/")
def source_list(
    request: Request,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
) -> HTMLResponse:
    rows = [_row(db, registry, settings, scheduler, s) for s in sources.user_sources(db, user)]
    return render(request, "sources/list.html", {"user": user, "rows": rows})


@router.get("/sources/new")
def new_source(request: Request, user: CurrentUser, registry: Registry) -> HTMLResponse:
    return _form_page(request, user, registry, None, blank_form_values(), {})


@router.post("/sources/new")
async def create_source(
    request: Request,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
    tasks: BackgroundTasks,
) -> Response:
    data = await _posted(request, user, registry)
    try:
        body = SourceCreate.model_validate(data)
        source = sources.create_source(
            db, user, source_columns(body, FORM_FIELDS), registry, settings
        )
    except (ValidationError, Invalid) as err:
        return _rejected(request, user, registry, None, data, err)
    _reschedule(scheduler, tasks, source)
    return RedirectResponse(f"/?created={source.id}", status.HTTP_303_SEE_OTHER)


@router.get("/sources/suggest")
def suggest(request: Request, user: CurrentUser, registry: Registry, url: str = "") -> HTMLResponse:
    adapters = registry.all(user.id)
    matches = suggest_adapters(adapters, url) if url else []
    context = {"adapters": adapters, "matches": matches, "url": url}
    return render(request, "sources/_suggest.html", context)


@router.get("/sources/params")
def params_fields(
    request: Request, user: CurrentUser, registry: Registry, adapter_id: str = "", url: str = ""
) -> HTMLResponse:
    definition = registry.get(adapter_id, user.id) if adapter_id else None
    context = {"definition": definition, "values": {}, "errors": {}, "pasted_url": url}
    return render(request, "sources/_params.html", context)


@router.post("/sources/preview")
async def preview(
    request: Request, user: CurrentUser, registry: Registry, settings: AppSettings
) -> HTMLResponse:
    data = await _posted(request, user, registry)
    try:
        source = _unsaved_source(user, SourcePatch.model_validate(_previewable(data)))
    except ValidationError as err:
        return render(request, "sources/_preview.html", {"problems": error_list(err)})
    problems = _preview_blockers(source, registry, settings)
    if problems:
        return render(request, "sources/_preview.html", {"problems": problems})
    result = await preview_source(
        source, registry, request.app.state.runner, request.app.state.scrape_cache, utcnow()
    )
    return render(request, "sources/_preview.html", {"preview": result, "source": source})


@router.get("/sources/{source_id}")
def edit_source(
    request: Request, source_id: int, db: Db, user: CurrentUser, registry: Registry
) -> HTMLResponse:
    source = sources.owned_source(db, user, source_id)
    return _form_page(request, user, registry, source, source_form_values(source), {})


@router.post("/sources/{source_id}")
async def update_source(
    request: Request,
    source_id: int,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
    tasks: BackgroundTasks,
) -> Response:
    source = sources.owned_source(db, user, source_id)
    data = await _posted(request, user, registry)
    try:
        columns = source_columns(SourceCreate.model_validate(data), FORM_FIELDS)
        with db.begin_nested():
            sources.update_source(source, columns, registry, settings)
    except (ValidationError, Invalid) as err:
        db.refresh(source)
        return _rejected(request, user, registry, source, data, err)
    _reschedule(scheduler, tasks, source)
    return RedirectResponse(f"/?saved={source.id}", status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/delete")
def delete_source(
    source_id: int, db: Db, user: CurrentUser, scheduler: AppScheduler, tasks: BackgroundTasks
) -> RedirectResponse:
    db.delete(sources.owned_source(db, user, source_id))
    tasks.add_task(scheduler.source_deleted, source_id)
    return RedirectResponse("/", status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/sync")
async def sync_now(
    request: Request,
    source_id: int,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
    scheduler: AppScheduler,
) -> HTMLResponse:
    """Runs the sync inside the request and swaps in the updated row."""
    sources.owned_source(db, user, source_id)
    db.commit()  # end this request's transaction, so it can't block the run's writes
    busy = await _sync_unless_busy(scheduler, source_id)
    with request.app.state.sessions() as fresh:  # the run wrote through its own session
        row = _row(fresh, registry, settings, scheduler, fresh.get(Source, source_id))
    return render(request, "sources/_row.html", {"row": row, "busy": busy})


async def _posted(request: Request, user: User, registry: AdapterRegistry) -> dict[str, Any]:
    """The form as a `SourcePatch` body; the chosen adapter says which params to read."""
    form = await request.form()
    definition = registry.get(str(form.get("adapter_id", "")), user.id)
    return source_form_data(form, definition)


def _row(
    db: Session,
    registry: AdapterRegistry,
    settings: Settings,
    scheduler: SyncScheduler,
    source: Source,
) -> SourceRow:
    definition = registry.get(source.adapter_id, source.user_id)
    matched = len(matched_events(db, source, utcnow()))
    return source_row(settings, source, definition, matched, scheduler.shown_run_at(source))


def _reschedule(scheduler: SyncScheduler, tasks: BackgroundTasks, source: Source) -> None:
    """After the request commits, so a due job can't run before the source is saved."""
    tasks.add_task(scheduler.schedule, source.id, scheduler.planned_run_at(source))


async def _sync_unless_busy(scheduler: SyncScheduler, source_id: int) -> bool:
    """Sync now; True when a run was already going, which finishes the job instead."""
    try:
        await scheduler.sync_now(source_id)
    except SyncInProgress:
        return True
    return False


def _previewable(data: dict[str, Any]) -> dict[str, Any]:
    """People fill in the name last; a blank one shouldn't hold back the preview."""
    return {**data, "name": data["name"] or None}


def _unsaved_source(user: User, body: SourcePatch) -> Source:
    """A source that's never added to the session, for previewing the form as it stands."""
    return Source(
        user_id=user.id,
        name=body.name or "",
        adapter_id=body.adapter_id or "",
        params_json=body.params or {},
        include_kw=body.include_kw or [],
        exclude_kw=body.exclude_kw or [],
        interval_min=body.interval_min,
        lookahead_days=body.lookahead_days or DEFAULT_LOOKAHEAD_DAYS,
    )


def _preview_blockers(
    source: Source, registry: AdapterRegistry, settings: Settings
) -> list[dict[str, str]]:
    """The preview only needs an adapter and its params; other problems wait for Save."""
    if not source.adapter_id:
        return [{"loc": "adapter_id", "msg": "pick an adapter to see a preview"}]
    problems = source_problems(source, registry, settings)
    return [p for p in problems if p["loc"] == "adapter_id" or p["loc"].startswith("params.")]


def _form_page(
    request: Request,
    user: User,
    registry: AdapterRegistry,
    source: Source | None,
    values: dict[str, Any],
    errors: dict[str, str],
    status_code: int = 200,
) -> HTMLResponse:
    adapters = registry.all(user.id)
    definition = registry.get(values["adapter_id"], user.id) if values["adapter_id"] else None
    context = {
        "user": user,
        "source": source,
        "adapters": adapters,
        "definition": definition,
        "values": values,
        "errors": errors,
        "param_prefix": PARAM_PREFIX,
    }
    return render(request, "sources/form.html", context, status_code=status_code)


def _rejected(
    request: Request,
    user: User,
    registry: AdapterRegistry,
    source: Source | None,
    data: dict[str, Any],
    err: ValidationError | Invalid,
) -> HTMLResponse:
    problems = error_list(err) if isinstance(err, ValidationError) else err.problems
    errors = {row["loc"]: row["msg"] for row in problems}
    values = echo_form_values(data)
    return _form_page(request, user, registry, source, values, errors, status_code=422)
