"""JSON API for sources and adapter definitions, for the web UI and other clients."""

import json
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition, Param, error_list
from app.db import AdapterDef, Db, Source, User
from app.feeds import feed_url
from app.settings import Settings
from app.store import DefinitionTextError, dump_yaml, load_row, load_yaml, parse_user_definition

LOCAL_USER_EMAIL = "local"
MAX_LOOKAHEAD_DAYS = 366
UNPROCESSABLE = 422
"""Starlette renamed its 422 constant; the number is stable."""

router = APIRouter(prefix="/api")


def current_user(db: Db) -> User:
    """The user a request acts as.

    Until Google sign-in exists, every request acts as one local user, created
    on first use. Sign-in replaces this dependency.
    """
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=LOCAL_USER_EMAIL)
        db.add(user)
        db.flush()
    return user


CurrentUser = Annotated[User, Depends(current_user, scope="function")]


def _registry(request: Request) -> AdapterRegistry:
    return request.app.state.adapters


def _settings(request: Request) -> Settings:
    return request.app.state.settings


Registry = Annotated[AdapterRegistry, Depends(_registry)]
AppSettings = Annotated[Settings, Depends(_settings)]


# Adapter definitions


class AdapterSummary(BaseModel):
    id: str
    name: str
    kind: str
    version: int
    builtin: bool


class AdapterDetail(AdapterSummary):
    definition: dict[str, Any]
    yaml: str


@router.get("/adapters")
def list_adapters(registry: Registry) -> list[AdapterSummary]:
    return [_summary(registry, definition) for definition in registry.all()]


@router.get("/adapters/{adapter_id}")
def get_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> AdapterDetail:
    builtin = registry.get(adapter_id) if registry.is_builtin(adapter_id) else None
    if builtin is not None:
        return _builtin_detail(builtin)
    return _user_detail(_owned_definition(db, user, adapter_id))


@router.post("/adapters", status_code=status.HTTP_201_CREATED)
async def create_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    definition, text = await _definition_body(request)
    _require_free_id(db, registry, definition.id)
    row = AdapterDef(id=definition.id, user_id=user.id, yaml=text, version=definition.version)
    db.add(row)
    db.flush()
    return _user_detail(row)


@router.put("/adapters/{adapter_id}")
async def replace_adapter(
    adapter_id: str, request: Request, db: Db, user: CurrentUser, registry: Registry
) -> AdapterDetail:
    _require_not_builtin(registry, adapter_id)
    row = _owned_definition(db, user, adapter_id)
    definition, text = await _definition_body(request)
    _require_same_id(adapter_id, definition)
    row.yaml, row.version = text, definition.version
    db.flush()
    return _user_detail(row)


@router.delete("/adapters/{adapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> Response:
    _require_not_builtin(registry, adapter_id)
    row = _owned_definition(db, user, adapter_id)
    _require_unused(db, adapter_id)
    db.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _summary(registry: AdapterRegistry, definition: AdapterDefinition) -> AdapterSummary:
    return AdapterSummary(
        id=definition.id,
        name=definition.name,
        kind=definition.kind,
        version=definition.version,
        builtin=registry.is_builtin(definition.id),
    )


def _builtin_detail(definition: AdapterDefinition) -> AdapterDetail:
    data = _definition_dict(definition)
    return AdapterDetail(
        id=definition.id,
        name=definition.name,
        kind=definition.kind,
        version=definition.version,
        builtin=True,
        definition=data,
        yaml=dump_yaml(data),
    )


def _user_detail(row: AdapterDef) -> AdapterDetail:
    definition = load_row(row)
    return AdapterDetail(
        id=definition.id,
        name=definition.name,
        kind=definition.kind,
        version=definition.version,
        builtin=False,
        definition=_definition_dict(definition),
        yaml=row.yaml,
    )


def _definition_dict(definition: AdapterDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", by_alias=True, exclude_defaults=True)


async def _definition_body(request: Request) -> tuple[AdapterDefinition, str]:
    """The request's definition, from YAML text or a JSON object, plus the YAML to store."""
    data, text = await _body_data(request)
    try:
        return parse_user_definition(data), text
    except ValidationError as err:
        raise HTTPException(UNPROCESSABLE, error_list(err)) from None


async def _body_data(request: Request) -> tuple[dict[str, Any], str]:
    """Keep YAML exactly as written, comments included; JSON bodies are stored as YAML."""
    body = (await request.body()).decode()
    try:
        if "yaml" in request.headers.get("content-type", ""):
            return load_yaml(body), body
        data = _load_json_object(body)
    except DefinitionTextError as err:
        raise HTTPException(UNPROCESSABLE, _error("(body)", err)) from None
    return data, dump_yaml(data)


def _load_json_object(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as err:
        raise DefinitionTextError(f"invalid JSON: {err}") from None
    if not isinstance(data, dict):
        raise DefinitionTextError("a definition must be a JSON object")
    return data


def _owned_definition(db: Session, user: User, adapter_id: str) -> AdapterDef:
    row = db.get(AdapterDef, adapter_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"adapter {adapter_id!r} not found")
    return row


def _require_free_id(db: Session, registry: AdapterRegistry, adapter_id: str) -> None:
    if registry.is_builtin(adapter_id) or db.get(AdapterDef, adapter_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"adapter id {adapter_id!r} is taken")


def _require_not_builtin(registry: AdapterRegistry, adapter_id: str) -> None:
    if registry.is_builtin(adapter_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "built-in adapters are read-only")


def _require_same_id(adapter_id: str, definition: AdapterDefinition) -> None:
    if definition.id != adapter_id:
        msg = f"id must stay {adapter_id!r}; create a new definition to change it"
        raise HTTPException(UNPROCESSABLE, _error("id", msg))


def _require_unused(db: Session, adapter_id: str) -> None:
    used = db.scalar(select(Source.id).where(Source.adapter_id == adapter_id).limit(1))
    if used is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"adapter {adapter_id!r} is used by sources")


def _error(loc: str, msg: object) -> list[dict[str, str]]:
    return [{"loc": loc, "msg": str(msg)}]


# Sources


class SourcePatch(BaseModel):
    """Fields a client may change; on create, `name` and `adapter_id` are required."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1)] | None = None
    adapter_id: str | None = None
    params: dict[str, Any] | None = None
    include_kw: list[str] | None = None
    exclude_kw: list[str] | None = None
    interval_min: int | None = None
    lookahead_days: Annotated[int, Field(ge=1, le=MAX_LOOKAHEAD_DAYS)] | None = None
    target_calendar_id: str | None = None
    enabled: bool | None = None


class SourceCreate(SourcePatch):
    name: Annotated[str, Field(min_length=1)]
    adapter_id: str


class SourceOut(BaseModel):
    id: int
    name: str
    adapter_id: str
    params: dict[str, Any]
    include_kw: list[str]
    exclude_kw: list[str]
    interval_min: int
    lookahead_days: int
    target_calendar_id: str | None
    enabled: bool
    feed_url: str
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None


_COLUMN_FOR = {"params": "params_json"}
"""API field names that differ from their column names."""


@router.get("/sources")
def list_sources(db: Db, user: CurrentUser, settings: AppSettings) -> list[SourceOut]:
    rows = db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.id))
    return [_source_out(settings, row) for row in rows]


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceCreate, db: Db, user: CurrentUser, registry: Registry, settings: AppSettings
) -> SourceOut:
    source = Source(user_id=user.id)
    _apply_changes(source, body, set(SourcePatch.model_fields), registry, settings)
    db.add(source)
    db.flush()
    return _source_out(settings, source)


@router.get("/sources/{source_id}")
def get_source(source_id: int, db: Db, user: CurrentUser, settings: AppSettings) -> SourceOut:
    return _source_out(settings, _owned_source(db, user, source_id))


@router.patch("/sources/{source_id}")
def update_source(
    source_id: int,
    body: SourcePatch,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    settings: AppSettings,
) -> SourceOut:
    source = _owned_source(db, user, source_id)
    _apply_changes(source, body, body.model_fields_set, registry, settings)
    db.flush()
    return _source_out(settings, source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, db: Db, user: CurrentUser) -> Response:
    db.delete(_owned_source(db, user, source_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owned_source(db: Session, user: User, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"source {source_id} not found")
    return source


def _apply_changes(
    source: Source,
    body: SourcePatch,
    fields: set[str],
    registry: AdapterRegistry,
    settings: Settings,
) -> None:
    """Copy the given fields onto the source, then validate the result as a whole."""
    for name in fields:
        value = getattr(body, name)
        if value is not None:
            setattr(source, _COLUMN_FOR.get(name, name), value)
    if "target_calendar_id" in fields:
        source.target_calendar_id = body.target_calendar_id
    _validate_source(source, registry, settings)


def _validate_source(source: Source, registry: AdapterRegistry, settings: Settings) -> None:
    problems = [
        *_interval_problems(source, settings),
        *_adapter_problems(source, registry),
    ]
    if problems:
        raise HTTPException(UNPROCESSABLE, problems)


def _interval_problems(source: Source, settings: Settings) -> list[dict[str, str]]:
    interval = source.interval_min if source.interval_min is not None else 360
    if interval < settings.min_interval_min:
        return _error("interval_min", f"must be at least {settings.min_interval_min} minutes")
    return []


def _adapter_problems(source: Source, registry: AdapterRegistry) -> list[dict[str, str]]:
    definition = registry.get(source.adapter_id)
    if definition is None:
        return _error("adapter_id", f"adapter {source.adapter_id!r} not found")
    return _param_problems(definition.params, source.params_json or {})


def _param_problems(declared: dict[str, Param], given: dict[str, Any]) -> list[dict[str, str]]:
    """Every given param must be declared; every declared param needs a value or a default."""
    problems = [
        {"loc": f"params.{name}", "msg": "not a parameter of this adapter"}
        for name in given
        if name not in declared
    ]
    for name, param in declared.items():
        msg = _param_problem(param, given.get(name))
        if msg:
            problems.append({"loc": f"params.{name}", "msg": msg})
    return problems


def _param_problem(param: Param, value: Any) -> str | None:
    if value is None:
        return "required" if param.default is None else None
    if param.type == "int":
        return None if isinstance(value, int) and not isinstance(value, bool) else "must be an int"
    if not isinstance(value, str):
        return "must be a string"
    if param.type == "url" and not _is_http_url(value):
        return "must be an http(s) URL"
    return None


def _is_http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _source_out(settings: Settings, source: Source) -> SourceOut:
    return SourceOut(
        id=source.id,
        name=source.name,
        adapter_id=source.adapter_id,
        params=source.params_json,
        include_kw=source.include_kw,
        exclude_kw=source.exclude_kw,
        interval_min=source.interval_min,
        lookahead_days=source.lookahead_days,
        target_calendar_id=source.target_calendar_id,
        enabled=source.enabled,
        feed_url=feed_url(settings, source.feed_token),
        last_run_at=source.last_run_at,
        last_status=source.last_status,
        last_error=source.last_error,
    )
