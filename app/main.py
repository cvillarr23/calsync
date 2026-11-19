"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.events import ENGINES
from app.adapters.fetch import FetchLimits
from app.adapters.html import HtmlEngine
from app.adapters.registry import AdapterRegistry
from app.api import router
from app.db.engine import init_db, make_engine
from app.services.definition_store import DefinitionStore
from app.settings import Settings, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database at startup, so building the app doesn't touch the data dir."""
    engine = make_engine(app.state.settings.data_dir)
    app.state.sessions = init_db(engine)
    app.state.adapters.add_source(DefinitionStore(app.state.sessions).definitions)
    yield
    engine.dispose()


def _register_engines(settings: Settings) -> None:
    """Engines need the instance's fetch limits, so they're registered once settings exist."""
    ENGINES["html"] = HtmlEngine(FetchLimits.from_settings(settings))


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="calsync", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.adapters = AdapterRegistry.with_builtins()
    _register_engines(app.state.settings)
    app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
