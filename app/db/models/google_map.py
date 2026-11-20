from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UtcDateTime


class GoogleMap(Base):
    """Which Google Calendar event mirrors each calsync event, and the hash it was synced at.

    `calendar_id` and `start_utc` are copied from the push, so a changed target and
    "future only" deletes can be decided after the event row itself is gone.
    """

    __tablename__ = "google_map"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    google_event_id: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    calendar_id: Mapped[str | None] = mapped_column(String)
    start_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
