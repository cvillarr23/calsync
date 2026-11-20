from dataclasses import dataclass, field
from datetime import datetime

from app.adapters.events import AdapterRunError, AdapterRunner, ScrapedEvent
from app.adapters.fetch import FetchError
from app.adapters.registry import AdapterRegistry
from app.db.models import Source
from app.services import filters
from app.services.preview.scrape_cache import ScrapeCache
from app.services.sync.scrape import params_with_defaults, scrape


@dataclass
class SourcePreview:
    """What a source would sync now: events that pass its filters and those they drop."""

    matched: list[ScrapedEvent] = field(default_factory=list)
    excluded: list[ScrapedEvent] = field(default_factory=list)
    error: str | None = None


async def preview_source(
    source: Source,
    registry: AdapterRegistry,
    runner: AdapterRunner,
    cache: ScrapeCache,
    now: datetime,
) -> SourcePreview:
    """Run (or reuse) the adapter for an unsaved source and split its events by the filters.

    Nothing is stored. Run errors come back in `error` rather than being raised.
    """
    try:
        events = await _cached_scrape(source, registry, runner, cache, now)
    except (AdapterRunError, FetchError) as err:
        return SourcePreview(error=str(err) or type(err).__name__)
    return _split(events, source)


async def _cached_scrape(
    source: Source,
    registry: AdapterRegistry,
    runner: AdapterRunner,
    cache: ScrapeCache,
    now: datetime,
) -> list[ScrapedEvent]:
    definition = registry.get(source.adapter_id, source.user_id)
    params = params_with_defaults(definition, source.params_json) if definition else {}
    key = ScrapeCache.key(definition, params, source.lookahead_days) if definition else None
    cached = cache.get(key) if key else None
    if cached is not None:
        return cached
    events = await scrape(source, registry, runner, now)
    if key:
        cache.put(key, events)
    return events


def _split(events: list[ScrapedEvent], source: Source) -> SourcePreview:
    preview = SourcePreview()
    for event in sorted(events, key=lambda e: e.start_utc):
        passes = filters.matches(event.title, source.include_kw, source.exclude_kw)
        (preview.matched if passes else preview.excluded).append(event)
    return preview
