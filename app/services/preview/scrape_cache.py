import json
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from app.adapters.events import ScrapedEvent
from app.adapters.schema import AdapterDefinition

Key = tuple[str, str, int]


class ScrapeCache:
    """Recent adapter results for the source form's preview.

    The preview re-renders on every keystroke in the keyword boxes, and the
    keywords don't change what the adapter returns, so only a change to the
    definition, params or lookahead runs the adapter again.
    """

    def __init__(
        self,
        ttl_s: float = 300.0,
        max_entries: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[Key, tuple[float, list[ScrapedEvent]]] = OrderedDict()

    @staticmethod
    def key(definition: AdapterDefinition, params: dict[str, Any], lookahead: int) -> Key:
        return (definition.model_dump_json(), json.dumps(params, sort_keys=True), lookahead)

    def get(self, key: Key) -> list[ScrapedEvent] | None:
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] > self._ttl_s:
            self._entries.pop(key, None)
            return None
        return entry[1]

    def put(self, key: Key, events: list[ScrapedEvent]) -> None:
        self._entries[key] = (self._clock(), events)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
