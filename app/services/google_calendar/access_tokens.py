"""Short-lived access tokens from the refresh tokens calsync stores for each user."""

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from cryptography.fernet import InvalidToken

from app.db.models import User
from app.services.auth.google import TIMEOUT_S, TOKEN_URL
from app.services.google_calendar.errors import CalendarApiError, GoogleReconnectNeeded
from app.services.google_calendar.retry import Sleep, send_with_backoff
from app.services.tokens import decrypt_token
from app.settings import Settings

EXPIRY_MARGIN_S = 60
"""Refresh this long before Google's expiry, so a token can't lapse mid-request."""


@dataclass(frozen=True)
class _Cached:
    token: str
    refresh_token_enc: str
    expires_at: float


class AccessTokens:
    """Trades a user's refresh token for an access token, cached until shortly before expiry.

    The cache is keyed on the stored refresh token too, so reconnecting Google drops it.
    """

    def __init__(
        self,
        settings: Settings,
        sleep: Sleep,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._transport = transport
        self._clock = clock
        self._cache: dict[int, _Cached] = {}

    async def token(self, user: User) -> str:
        cached = self._cache.get(user.id)
        if self._usable(cached, user):
            return cached.token
        refresh_token = self._refresh_token(user)
        token, expires_in = await self._refresh(refresh_token)
        expires_at = self._clock() + expires_in - EXPIRY_MARGIN_S
        self._cache[user.id] = _Cached(token, user.refresh_token_enc, expires_at)
        return token

    def forget(self, user: User) -> None:
        """Drop the cached token, after Google said it is no longer valid."""
        self._cache.pop(user.id, None)

    def _usable(self, cached: _Cached | None, user: User) -> bool:
        if cached is None or cached.refresh_token_enc != user.refresh_token_enc:
            return False
        return cached.expires_at > self._clock()

    def _refresh_token(self, user: User) -> str:
        """The decrypted refresh token; one sealed with a different key can't be used."""
        if user.refresh_token_enc is None:
            raise GoogleReconnectNeeded
        try:
            return decrypt_token(self._settings, user.refresh_token_enc)
        except InvalidToken:
            raise GoogleReconnectNeeded from None

    async def _refresh(self, refresh_token: str) -> tuple[str, float]:
        response = await self._post_refresh(refresh_token)
        if response.status_code in (400, 401) and _grant_lost(response):
            raise GoogleReconnectNeeded
        if response.status_code != 200:
            raise CalendarApiError(
                f"Google's token endpoint answered {response.status_code}", response.status_code
            )
        body = response.json()
        return body["access_token"], float(body.get("expires_in", 3600))

    async def _post_refresh(self, refresh_token: str) -> httpx.Response:
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret.get_secret_value(),
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S) as client:
            return await send_with_backoff(lambda: client.post(TOKEN_URL, data=form), self._sleep)


def _grant_lost(response: httpx.Response) -> bool:
    try:
        return response.json().get("error") in {"invalid_grant", "unauthorized_client"}
    except ValueError:
        return False
