"""One module per table. Importing this package registers every table on `Base.metadata`."""

from app.db.models.adapter_def import AdapterDef
from app.db.models.event import Event
from app.db.models.google_map import GoogleMap
from app.db.models.schema_version import SchemaVersion
from app.db.models.source import Source
from app.db.models.user import User

__all__ = ["AdapterDef", "Event", "GoogleMap", "SchemaVersion", "Source", "User"]
