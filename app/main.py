"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

from fastapi import FastAPI

from app.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="calsync")
    app.state.settings = settings or load_settings()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
