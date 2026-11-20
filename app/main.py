"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.events import ENGINES
from app.adapters.fetch import FetchLimits
from app.adapters.html import HtmlEngine
from app.adapters.pipeline import PipelineEngine
from app.adapters.registry import AdapterRegistry
from app.api import router
from app.api.errors import add_error_handlers
from app.db.engine import init_db, make_engine
from app.services.definition_store import DefinitionStore
from app.services.scheduling import SourceRuns, SyncScheduler
from app.settings import Settings, load_settings


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
    runs = SourceRuns(app.state.sessions, app.state.adapters)
    scheduler = SyncScheduler(runs, app.state.sessions, app.state.settings)
    scheduler.start(paused=not app.state.run_scheduler)
    scheduler.schedule_all()
    return scheduler


def _register_engines(settings: Settings) -> None:
    """Engines need the instance's fetch limits, so they're registered once settings exist."""
    limits = FetchLimits.from_settings(settings)
    ENGINES["html"] = HtmlEngine(limits)
    ENGINES["pipeline"] = PipelineEngine(limits)


def create_app(settings: Settings | None = None, *, run_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="calsync", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.run_scheduler = run_scheduler
    app.state.adapters = AdapterRegistry.with_builtins()
    _register_engines(app.state.settings)
    app.include_router(router)
    add_error_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
