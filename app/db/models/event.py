from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UtcDateTime


class Event(Base):
    """The latest copy of each event an adapter produced for a source, filtered or not."""

    __tablename__ = "events"

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    start_utc: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    end_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
