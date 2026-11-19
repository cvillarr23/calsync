"""What an adapter run produces, and the runner contract the sync core calls.

Each adapter kind's engine turns a definition plus a source's params into a
list of `ScrapedEvent`s for a time window. The sync core only depends on
`AdapterRunner`, so engines and tests can be swapped in.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.adapters.schema import AdapterDefinition


@dataclass(frozen=True)
class ScrapedEvent:
    """One event from an adapter run. Datetimes are timezone-aware UTC.

    `uid` is stable across runs for the same real-world event; the engine
    derives it from the definition's `uid` fields or its own defaults.
    """

    uid: str
    title: str
    start_utc: datetime
    end_utc: datetime | None = None
    location: str | None = None
    description: str | None = None
    url: str | None = None


AdapterRunner = Callable[
    [AdapterDefinition, Mapping[str, Any], datetime, datetime],
    Awaitable[list[ScrapedEvent]],
]
"""`await runner(definition, params, window_start, window_end)` -> events in the window."""


class AdapterRunError(RuntimeError):
    """An adapter run failed; the message is shown to the user as the source's last error."""


ENGINES: dict[str, AdapterRunner] = {}
"""Engine per adapter kind. Each kind's engine module registers itself here."""


async def default_runner(
    definition: AdapterDefinition,
    params: Mapping[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> list[ScrapedEvent]:
    """Run a definition with the engine registered for its kind."""
    engine = ENGINES.get(definition.kind)
    if engine is None:
        raise AdapterRunError(f"no engine for adapter kind {definition.kind!r} yet")
    return await engine(definition, params, window_start, window_end)
