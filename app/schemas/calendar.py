from pydantic import BaseModel


class CalendarOut(BaseModel):
    """A Google Calendar the user can pick as a source's target."""

    id: str
    summary: str
    primary: bool
