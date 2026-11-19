"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.registry import AdapterRegistry
from app.adapters.routes import router as adapter_router
from app.api import router as api_router
from app.db import init_db, make_engine
from app.feeds import router as feed_router
from app.settings import Settings, load_settings
from app.store import DefinitionStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database at startup, so building the app doesn't touch the data dir."""
    engine = make_engine(app.state.settings.data_dir)
    app.state.sessions = init_db(engine)
    app.state.adapters.add_source(DefinitionStore(app.state.sessions).definitions)
    yield
    engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="calsync", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.adapters = AdapterRegistry.with_builtins()
    app.include_router(adapter_router)
    app.include_router(api_router)
    app.include_router(feed_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
