from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import User
from app.services.google_calendar.calendar import Calendar
from app.services.google_calendar.connection import GoogleConnection
from app.services.google_calendar.errors import CalendarApiError, GoogleReconnectNeeded
from app.services.users import forget_google_grant


@dataclass(frozen=True)
class CalendarChoices:
    """The source form's target calendars, or why they couldn't be listed."""

    calendars: list[Calendar] = field(default_factory=list)
    problem: str | None = None
    reconnect: bool = False


async def calendar_choices(
    db: Session, connection: GoogleConnection, user: User
) -> CalendarChoices:
    """A failed listing still lets the form save; only the dropdown is left short."""
    try:
        return CalendarChoices(await connection.calendars(user))
    except GoogleReconnectNeeded as err:
        forget_google_grant(db, user.id)
        return CalendarChoices(problem=str(err), reconnect=True)
    except CalendarApiError as err:
        return CalendarChoices(problem=f"couldn't list your calendars: {err}")
