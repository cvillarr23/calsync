"""Rendering Jinja2 pages and htmx fragments, with what every template needs."""

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.csrf import csrf_token
from app.services.error_hints import run_hint

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _utc(value: datetime | None) -> str:
    """Server-side text for a time; `app.js` rewrites it in the viewer's time zone."""
    return f"{value:%Y-%m-%d %H:%M} UTC" if value else ""


TEMPLATES.env.filters["utc"] = _utc
TEMPLATES.env.globals["run_hint"] = run_hint


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    page = {"csrf_token": csrf_token(request), **(context or {})}
    return TEMPLATES.TemplateResponse(request, name, page, status_code=status_code, headers=headers)
