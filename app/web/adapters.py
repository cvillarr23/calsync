"""The adapter pages: the list, the YAML editor with validation and Test with params,
export and import."""

import re
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from app.adapters.fetch import FetchLimits
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition
from app.api.deps import AppSettings, CurrentUser, Registry
from app.db.base import utcnow
from app.db.models import User
from app.db.session import Db
from app.mappers.adapter import builtin_detail
from app.mappers.pages import problem_rows
from app.mappers.source_form import PARAM_PREFIX, form_params
from app.services import adapter_defs
from app.services.error_hints import run_hint
from app.services.errors import Conflict, Invalid
from app.services.preview import try_definition
from app.web.rendering import render

router = APIRouter(prefix="/adapters")

DEFAULT_TEST_DAYS = 14
STARTER_YAML = """\
# A new adapter definition. Edit it, click Test with params, then Save.
# Reference: https://cvillarr23.github.io/calsync/adapters/
id: my-calendar
version: 1
name: My calendar
kind: html
params:
  url: {type: url, description: The calendar page}
match_hosts: []
fetch:
  url: "{{url}}"
item: .event
map:
  title: {selector: h3}
  start: {selector: time, attr: datetime}
"""
_ID_LINE = re.compile(r"^id:.*$", re.MULTILINE)


@router.get("")
def adapter_list(request: Request, user: CurrentUser, registry: Registry) -> HTMLResponse:
    definitions = registry.all(user.id)
    builtin = {d.id for d in definitions if registry.is_builtin(d.id)}
    context = {"user": user, "definitions": definitions, "builtin": builtin}
    return render(request, "adapters/list.html", context)


@router.get("/new")
def new_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry, copy: str = ""
) -> HTMLResponse:
    text = _copied_yaml(db, user, registry, copy) if copy else STARTER_YAML
    return _editor(request, user, text=text, mode="new")


@router.get("/import")
def import_page(request: Request, user: CurrentUser) -> HTMLResponse:
    return render(request, "adapters/import.html", {"user": user, "text": "", "problems": []})


@router.post("/import")
async def import_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry
) -> Response:
    text = await _form_text(request)
    try:
        definition, stored = adapter_defs.parse_text(text, is_yaml=True)
        adapter_defs.create_definition(db, user, registry, definition, stored)
    except (Invalid, Conflict) as err:
        context = {"user": user, "text": text, "problems": _problems(text, err)}
        return render(request, "adapters/import.html", context, status_code=_status(err))
    return RedirectResponse(f"/adapters/{definition.id}?saved=1", status.HTTP_303_SEE_OTHER)


@router.post("/validate")
async def validate(request: Request) -> HTMLResponse:
    """Re-run on every edit: the problems list, plus the test params form (out of band)."""
    form = await request.form()
    text = str(form.get("yaml", ""))
    try:
        definition, _ = adapter_defs.parse_text(text, is_yaml=True)
    except Invalid as err:
        return render(request, "adapters/_validation.html", {"problems": _problems(text, err)})
    context = {"definition": definition, "values": _param_values(form), "oob": True}
    return render(request, "adapters/_validation.html", context)


@router.post("/test")
async def test_with_params(request: Request, settings: AppSettings) -> HTMLResponse:
    form = await request.form()
    text = str(form.get("yaml", ""))
    try:
        definition, _ = adapter_defs.parse_text(text, is_yaml=True)
    except Invalid as err:
        return render(request, "adapters/_trial.html", {"problems": _problems(text, err)})
    trial = await try_definition(
        definition,
        form_params(form, definition),
        utcnow(),
        _days(form.get("days")),
        limits=FetchLimits.from_settings(settings),
        cache=request.app.state.page_cache,
        **request.app.state.fetch_options,
    )
    context = {"trial": trial, "hint": run_hint(trial.error)}
    return render(request, "adapters/_trial.html", context)


@router.post("")
async def create_adapter(
    request: Request, db: Db, user: CurrentUser, registry: Registry
) -> Response:
    text = await _form_text(request)
    try:
        definition, _ = adapter_defs.parse_text(text, is_yaml=True)
        adapter_defs.create_definition(db, user, registry, definition, text)
    except (Invalid, Conflict) as err:
        return _editor(request, user, text=text, mode="new", err=err)
    return RedirectResponse(f"/adapters/{definition.id}?saved=1", status.HTTP_303_SEE_OTHER)


@router.get("/{adapter_id}.yaml")
def export_adapter(adapter_id: str, db: Db, user: CurrentUser, registry: Registry) -> Response:
    text = _yaml_of(db, user, registry, adapter_id)
    disposition = f'attachment; filename="{adapter_id}.yaml"'
    return PlainTextResponse(
        text, media_type="application/yaml", headers={"Content-Disposition": disposition}
    )


@router.get("/{adapter_id}")
def edit_adapter(
    request: Request,
    adapter_id: str,
    db: Db,
    user: CurrentUser,
    registry: Registry,
    saved: bool = False,
) -> HTMLResponse:
    text = _yaml_of(db, user, registry, adapter_id)
    mode = "builtin" if registry.is_builtin(adapter_id) else "edit"
    return _editor(request, user, text=text, mode=mode, adapter_id=adapter_id, saved=saved)


@router.post("/{adapter_id}")
async def save_adapter(
    request: Request, adapter_id: str, db: Db, user: CurrentUser, registry: Registry
) -> Response:
    adapter_defs.require_not_builtin(registry, adapter_id)
    row = adapter_defs.owned_definition(db, user, adapter_id)
    text = await _form_text(request)
    try:
        definition, _ = adapter_defs.parse_text(text, is_yaml=True)
        adapter_defs.replace_definition(db, registry, row, definition, text)
    except (Invalid, Conflict) as err:
        return _editor(request, user, text=text, mode="edit", adapter_id=adapter_id, err=err)
    return RedirectResponse(f"/adapters/{adapter_id}?saved=1", status.HTTP_303_SEE_OTHER)


@router.post("/{adapter_id}/delete")
def delete_adapter(
    request: Request, adapter_id: str, db: Db, user: CurrentUser, registry: Registry
) -> Response:
    adapter_defs.require_not_builtin(registry, adapter_id)
    row = adapter_defs.owned_definition(db, user, adapter_id)
    adapter_defs.delete_definition(db, registry, row)
    return RedirectResponse("/adapters", status.HTTP_303_SEE_OTHER)


def _editor(
    request: Request,
    user: User,
    *,
    text: str,
    mode: str,
    adapter_id: str | None = None,
    saved: bool = False,
    err: Invalid | Conflict | None = None,
) -> HTMLResponse:
    definition = _parsed_or_none(text)
    context = {
        "user": user,
        "text": text,
        "mode": mode,
        "adapter_id": adapter_id,
        "saved": saved,
        "definition": definition,
        "values": {},
        "problems": _problems(text, err) if err else [],
        "test_days": DEFAULT_TEST_DAYS,
        "param_prefix": PARAM_PREFIX,
    }
    return render(request, "adapters/editor.html", context, status_code=_status(err))


def _yaml_of(db: Db, user: User, registry: AdapterRegistry, adapter_id: str) -> str:
    """Built-ins as YAML dumped from the definition; user definitions exactly as written."""
    builtin = registry.get(adapter_id) if registry.is_builtin(adapter_id) else None
    if builtin is not None:
        return builtin_detail(builtin).yaml
    return adapter_defs.owned_definition(db, user, adapter_id).yaml


def _copied_yaml(db: Db, user: User, registry: AdapterRegistry, adapter_id: str) -> str:
    """Another definition's YAML under a new id, comments kept, for "Copy as new"."""
    text = _yaml_of(db, user, registry, adapter_id)
    return _ID_LINE.sub(f"id: {adapter_id}-copy", text, count=1)


def _parsed_or_none(text: str) -> AdapterDefinition | None:
    try:
        return adapter_defs.parse_text(text, is_yaml=True)[0]
    except Invalid:
        return None


def _problems(text: str, err: Invalid | Conflict) -> list[Any]:
    if isinstance(err, Invalid):
        return problem_rows(text, err.problems)
    return problem_rows(text, [{"loc": "id", "msg": str(err)}])


def _status(err: Invalid | Conflict | None) -> int:
    if err is None:
        return status.HTTP_200_OK
    return status.HTTP_409_CONFLICT if isinstance(err, Conflict) else 422


async def _form_text(request: Request) -> str:
    return str((await request.form()).get("yaml", ""))


def _param_values(form: Any) -> dict[str, str]:
    """The test params typed so far, so re-rendering the fields keeps them."""
    return {
        key.removeprefix(PARAM_PREFIX): str(value)
        for key, value in form.items()
        if key.startswith(PARAM_PREFIX)
    }


def _days(value: Any) -> int:
    try:
        return max(1, min(int(str(value)), 366))
    except (TypeError, ValueError):
        return DEFAULT_TEST_DAYS
