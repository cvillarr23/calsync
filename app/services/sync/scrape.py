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
    definition = registry.get(source.adapter_id, source.user_id)
    if definition is None:
        raise AdapterRunError(f"adapter {source.adapter_id!r} not found")
    window_end = now + timedelta(days=source.lookahead_days)
    params = params_with_defaults(definition, source.params_json or {})
    return await runner(definition, params, now, window_end)


def params_with_defaults(definition: AdapterDefinition, given: dict[str, Any]) -> dict[str, Any]:
    """The given params over the definition's defaults."""
    defaults = {
        name: param.default
        for name, param in definition.params.items()
        if param.default is not None
    }
    return {**defaults, **given}
