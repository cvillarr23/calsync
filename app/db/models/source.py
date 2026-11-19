import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UtcDateTime

DEFAULT_INTERVAL_MIN = 360
DEFAULT_LOOKAHEAD_DAYS = 60


def new_feed_token() -> str:
    return secrets.token_urlsafe(24)


class Source(Base):
    """A calendar page to sync: which adapter reads it, its filters, schedule and outputs."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    adapter_id: Mapped[str] = mapped_column(String, index=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    include_kw: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_kw: Mapped[list[str]] = mapped_column(JSON, default=list)
    interval_min: Mapped[int] = mapped_column(Integer, default=DEFAULT_INTERVAL_MIN)
    lookahead_days: Mapped[int] = mapped_column(Integer, default=DEFAULT_LOOKAHEAD_DAYS)
    target_calendar_id: Mapped[str | None] = mapped_column(String)
    feed_token: Mapped[str] = mapped_column(String, unique=True, default=new_feed_token)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_status: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
