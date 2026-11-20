"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.events import ENGINES, default_runner
from app.adapters.fetch import FetchLimits, PageCache
from app.adapters.html import HtmlEngine
from app.adapters.pipeline import PipelineEngine
from app.adapters.registry import AdapterRegistry
from app.api import router
from app.db.engine import init_db, make_engine
from app.services.auth import GoogleOAuth
from app.services.definition_store import DefinitionStore
from app.services.google_calendar import GoogleConnection
from app.services.preview import ScrapeCache
from app.services.scheduling import SourceRuns, SyncScheduler
from app.services.sync.google_targets import google_targets
from app.settings import Settings, load_settings
from app.web import mount_web
from app.web.errors import add_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database and start the scheduler at startup, so building the app doesn't
    touch the data dir. On shutdown, in-flight syncs get to finish before the database closes."""
    engine = make_engine(app.state.settings.data_dir)
    app.state.sessions = init_db(engine)
    app.state.adapters.add_source(DefinitionStore(app.state.sessions).definitions)
    app.state.scheduler = _start_scheduler(app)
    yield
    await app.state.scheduler.shutdown()
    engine.dispose()


def _start_scheduler(app: FastAPI) -> SyncScheduler:
    """Schedule every enabled source. With `run_scheduler` off, jobs are kept but never fire."""
    targets = google_targets(app.state.google_calendar)
    runs = SourceRuns(app.state.sessions, app.state.adapters, app.state.runner, targets)
    scheduler = SyncScheduler(runs, app.state.sessions, app.state.settings)
    scheduler.start(paused=not app.state.run_scheduler)
    scheduler.schedule_all()
    return scheduler


def _register_engines(settings: Settings) -> None:
    """Engines need the instance's fetch limits, so they're registered once settings exist."""
    limits = FetchLimits.from_settings(settings)
    ENGINES["html"] = HtmlEngine(limits)
    ENGINES["pipeline"] = PipelineEngine(limits)


def _set_services(app: FastAPI, settings: Settings) -> None:
    """Collaborators routes reach through `app.state`, so tests can swap in fakes."""
    app.state.google = GoogleOAuth(settings)
    app.state.google_calendar = GoogleConnection(settings)
    app.state.runner = default_runner
    app.state.scrape_cache = ScrapeCache()
    app.state.page_cache = PageCache()
    app.state.fetch_options = {}


def create_app(settings: Settings | None = None, *, run_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="calsync", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.run_scheduler = run_scheduler
    app.state.adapters = AdapterRegistry.with_builtins()
    _register_engines(app.state.settings)
    _set_services(app, app.state.settings)
    app.include_router(router)
    mount_web(app, app.state.settings)
    add_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
