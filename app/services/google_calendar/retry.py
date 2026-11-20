"""Retrying Google API requests that hit rate limits or server errors."""

import random
from collections.abc import Awaitable, Callable

import httpx

from app.services.google_calendar.errors import CalendarApiError

Sleep = Callable[[float], Awaitable[None]]

MAX_ATTEMPTS = 4
BASE_DELAY_S = 1.0
MAX_DELAY_S = 16.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}


async def send_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]], sleep: Sleep
) -> httpx.Response:
    """Send, retrying throttled and failed attempts with exponential backoff.

    The last attempt's response is returned whatever its status, for the caller to check.
    """
    for attempt in range(MAX_ATTEMPTS - 1):
        try:
            response = await send()
        except httpx.TransportError:
            await sleep(_backoff(attempt))
            continue
        if not _retryable(response):
            return response
        await sleep(_delay(response, attempt))
    return await _last_attempt(send)


async def _last_attempt(send: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
    try:
        return await send()
    except httpx.TransportError as err:
        raise CalendarApiError(f"couldn't reach Google: {err}") from None


def _retryable(response: httpx.Response) -> bool:
    """Google reports some rate limits as 403 with a rate-limit reason, not as 429."""
    if response.status_code in RETRY_STATUSES:
        return True
    return response.status_code == 403 and error_reason(response) in RATE_LIMIT_REASONS


def error_reason(response: httpx.Response) -> str | None:
    """The `reason` of the first error in a Google API error body, if it has one."""
    try:
        return response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "")
    if retry_after.isdigit():
        return min(float(retry_after), MAX_DELAY_S)
    return _backoff(attempt)


def _backoff(attempt: int) -> float:
    """1 s, 2 s, 4 s… with jitter, so runs throttled together don't retry together."""
    return min(BASE_DELAY_S * 2**attempt + random.uniform(0, BASE_DELAY_S), MAX_DELAY_S)
