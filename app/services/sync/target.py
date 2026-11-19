from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models import Event, Source


class SyncTarget(Protocol):
    """Somewhere matched events are pushed after they are stored, e.g. a Google Calendar."""

    async def apply(
        self, db: Session, source: Source, matched: Sequence[Event], now: datetime
    ) -> None: ...
