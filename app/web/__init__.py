"""The web UI: Jinja2 pages and htmx fragments over the same services as the JSON API."""

from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.csrf import require_csrf
from app.settings import Settings
from app.web import adapters, auth, sources

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "calsync_session"
SESSION_MAX_AGE_S = 30 * 24 * 3600

router = APIRouter()
router.include_router(auth.router)
router.include_router(sources.router, dependencies=[Depends(require_csrf)])
router.include_router(adapters.router, dependencies=[Depends(require_csrf)])


def mount_web(app: FastAPI, settings: Settings) -> None:
    """Pages, static files and the signed session cookie they rely on.

    The cookie is `SameSite=Lax`: Google's redirect back to `/auth/callback` is a
    top-level navigation, which Lax allows, while cross-site posts carry no cookie.
    """
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE_S,
        same_site="lax",
        https_only=settings.base_url.scheme == "https",
    )
