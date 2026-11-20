"""HTTP routes. Each resource has its own router module; `router` combines them."""

from fastapi import APIRouter, Depends

from app.api import adapters, feeds, schema, sources
from app.api.csrf import require_csrf
from app.api.deps import current_user

router = APIRouter()
router.include_router(schema.router)
_SIGNED_IN = [Depends(current_user), Depends(require_csrf)]
router.include_router(adapters.router, prefix="/api", dependencies=_SIGNED_IN)
router.include_router(sources.router, prefix="/api", dependencies=_SIGNED_IN)
router.include_router(feeds.router)
