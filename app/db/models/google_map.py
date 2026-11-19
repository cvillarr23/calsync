from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoogleMap(Base):
    """Which Google Calendar event mirrors each calsync event, and the hash it was synced at."""

    __tablename__ = "google_map"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    google_event_id: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
