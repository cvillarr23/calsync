"""HTTP routes. Each resource has its own router module; `router` combines them."""

from fastapi import APIRouter

from app.api import adapters, feeds, schema, sources

router = APIRouter()
router.include_router(schema.router)
router.include_router(adapters.router, prefix="/api")
router.include_router(sources.router, prefix="/api")
router.include_router(feeds.router)
