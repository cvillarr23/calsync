"""`/api/calendars`: the Google Calendars a source can sync to."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, GoogleCalendar
from app.db.session import Db
from app.schemas.calendar import CalendarOut
from app.services.errors import Conflict
from app.services.google_calendar import CalendarApiError, GoogleReconnectNeeded
from app.services.users import forget_google_grant

router = APIRouter(prefix="/calendars")


@router.get("")
async def list_calendars(db: Db, user: CurrentUser, google: GoogleCalendar) -> list[CalendarOut]:
    """Calendars the user can add events to. 409 means Google needs reconnecting."""
    try:
        calendars = await google.calendars(user)
    except GoogleReconnectNeeded as err:
        forget_google_grant(db, user.id)
        raise Conflict(str(err)) from err
    except CalendarApiError as err:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(err)) from err
    return [CalendarOut(id=c.id, summary=c.summary, primary=c.primary) for c in calendars]
