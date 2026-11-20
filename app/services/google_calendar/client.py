"""One user's Google Calendar, over the Calendar v3 REST API."""

from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

from app.db.models import User
from app.services.google_calendar.access_tokens import AccessTokens
from app.services.google_calendar.calendar import Calendar
from app.services.google_calendar.errors import CalendarApiError, GoogleReconnectNeeded
from app.services.google_calendar.retry import Sleep, error_reason, send_with_backoff

API_URL = "https://www.googleapis.com/calendar/v3"
TIMEOUT_S = 15.0
GONE = {404, 410}


class GoogleCalendarClient:
    """Calendar requests as `user`, used as `async with client:` around a batch of calls.

    404 and 410 on an event mean it's gone; the event methods report that instead of raising.
    """

    def __init__(
        self,
        access: AccessTokens,
        user: User,
        sleep: Sleep,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._access = access
        self._user = user
        self._sleep = sleep
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._http = httpx.AsyncClient(
            base_url=API_URL, transport=self._transport, timeout=TIMEOUT_S
        )
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
        self._http = None

    async def list_calendars(self) -> list[Calendar]:
        """Calendars the user can add events to, primary first."""
        items: list[dict[str, Any]] = []
        params: dict[str, str] = {"minAccessRole": "writer"}
        while True:
            body = _checked(await self._request("GET", "/users/me/calendarList", params=params))
            items.extend(body.get("items", []))
            if not body.get("nextPageToken"):
                break
            params = {**params, "pageToken": body["nextPageToken"]}
        return sorted((_calendar(item) for item in items), key=_calendar_order)

    async def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any] | None:
        response = await self._request("GET", _event_path(calendar_id, event_id))
        return None if response.status_code in GONE else _checked(response)

    async def insert_event(self, calendar_id: str, body: dict[str, Any]) -> str:
        response = await self._request("POST", _events_path(calendar_id), json=body)
        if response.status_code in GONE:
            raise CalendarApiError(
                f"calendar {calendar_id!r} was not found; pick another target calendar",
                response.status_code,
            )
        return _checked(response)["id"]

    async def patch_event(self, calendar_id: str, event_id: str, body: dict[str, Any]) -> bool:
        """False when the event is gone, so the caller can insert it again."""
        response = await self._request("PATCH", _event_path(calendar_id, event_id), json=body)
        if response.status_code in GONE:
            return False
        _checked(response)
        return True

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        response = await self._request("DELETE", _event_path(calendar_id, event_id))
        if response.status_code not in GONE:
            _checked(response)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A 401 means the cached access token died early: refresh once, then give up."""
        response = await self._authorized(method, path, **kwargs)
        if response.status_code == 401:
            self._access.forget(self._user)
            response = await self._authorized(method, path, **kwargs)
        if response.status_code == 401:
            raise GoogleReconnectNeeded
        return response

    async def _authorized(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._http is None:
            raise RuntimeError("use the client as `async with client:`")
        token = await self._access.token(self._user)
        headers = {"Authorization": f"Bearer {token}"}
        http = self._http
        return await send_with_backoff(
            lambda: http.request(method, path, headers=headers, **kwargs), self._sleep
        )


def _checked(response: httpx.Response) -> dict[str, Any]:
    """The JSON body of a successful response; any other status raises."""
    if response.is_success:
        return response.json() if response.content else {}
    reason = error_reason(response)
    detail = f" ({reason})" if reason else ""
    raise CalendarApiError(
        f"Google Calendar answered {response.status_code}{detail}", response.status_code
    )


def _events_path(calendar_id: str) -> str:
    """Calendar ids contain `@` and sometimes `#`, so they're escaped as one path segment."""
    return f"/calendars/{quote(calendar_id, safe='')}/events"


def _event_path(calendar_id: str, event_id: str) -> str:
    return f"{_events_path(calendar_id)}/{quote(event_id, safe='')}"


def _calendar(item: dict[str, Any]) -> Calendar:
    summary = item.get("summaryOverride") or item.get("summary") or item["id"]
    return Calendar(id=item["id"], summary=summary, primary=bool(item.get("primary")))


def _calendar_order(calendar: Calendar) -> tuple[bool, str]:
    return (not calendar.primary, calendar.summary.casefold())
