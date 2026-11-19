from datetime import datetime, timedelta
from typing import Any

from app.adapters.events import AdapterRunError, AdapterRunner, ScrapedEvent
from app.adapters.registry import AdapterRegistry
from app.adapters.schema import AdapterDefinition
from app.db.models import Source


async def scrape(
    source: Source, registry: AdapterRegistry, runner: AdapterRunner, now: datetime
) -> list[ScrapedEvent]:
    """Run the source's adapter from now to the end of its lookahead window."""
    definition = registry.get(source.adapter_id)
    if definition is None:
        raise AdapterRunError(f"adapter {source.adapter_id!r} not found")
    window_end = now + timedelta(days=source.lookahead_days)
    return await runner(definition, _params(definition, source), now, window_end)


def _params(definition: AdapterDefinition, source: Source) -> dict[str, Any]:
    """The source's params over the definition's defaults."""
    defaults = {
        name: param.default
        for name, param in definition.params.items()
        if param.default is not None
    }
    return {**defaults, **source.params_json}
