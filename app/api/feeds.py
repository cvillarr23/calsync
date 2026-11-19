"""`GET /feeds/{token}.ics`: a source's matched upcoming events, for anyone with the token.

There is no login on this route. The unguessable token in the URL is the
access control, so calendar apps can subscribe without credentials.
"""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.errors import not_found
from app.db.base import utcnow
from app.db.models import Source
from app.db.session import Db
from app.services.feeds import render_calendar
from app.services.sync import matched_events

router = APIRouter()


@router.get("/feeds/{feed_token}.ics")
def feed(feed_token: str, db: Db) -> Response:
    source = db.scalar(select(Source).where(Source.feed_token == feed_token))
    if source is None:
        raise not_found("feed not found")
    now = utcnow()
    body = render_calendar(source, matched_events(db, source, now), now)
    return Response(body, media_type="text/calendar; charset=utf-8")
