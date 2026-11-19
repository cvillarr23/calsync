"""Turn one extracted item into a `ScrapedEvent`, using a definition's field `map`.

This part is shared by every adapter kind. A kind supplies only a `Reader`, which
reads a field's raw value from its own kind of item (an HTML node, a JSON record).
Everything after that is the same for every kind: `regex` and `strip`, date and
time parsing, time zones, time ranges, default durations, `skip_if` and the uid.
"""

from app.adapters.mappers.errors import FieldFailure
from app.adapters.mappers.item import Reader, map_item
from app.adapters.mappers.window import Window

__all__ = ["FieldFailure", "Reader", "Window", "map_item"]
