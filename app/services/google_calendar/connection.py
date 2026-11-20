import asyncio

import httpx

from app.db.models import User
from app.services.google_calendar.access_tokens import AccessTokens
from app.services.google_calendar.calendar import Calendar
from app.services.google_calendar.client import GoogleCalendarClient
from app.services.google_calendar.retry import Sleep
from app.settings import Settings


class GoogleConnection:
    """The instance's link to Google Calendar: one access-token cache shared by every run.

    `transport` and `sleep` let tests stand in for Google and skip the backoff waits.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self._access = AccessTokens(settings, sleep, transport)

    def client(self, user: User) -> GoogleCalendarClient:
        return GoogleCalendarClient(self._access, user, self._sleep, self._transport)

    async def calendars(self, user: User) -> list[Calendar]:
        async with self.client(user) as client:
            return await client.list_calendars()
