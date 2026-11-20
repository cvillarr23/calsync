"""Google OpenID Connect over plain httpx: the authorization URL and the code exchange."""

import base64
import binascii
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services.auth.identity import Identity
from app.settings import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)
TIMEOUT_S = 10.0


class OAuthError(RuntimeError):
    """The code exchange failed or returned an ID token we can't accept."""


class GoogleOAuth:
    """Builds the sign-in redirect and turns the callback's code into an `Identity`.

    `transport` lets tests stand in for Google's token endpoint.
    """

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._client_id = settings.google_client_id
        self._client_secret = settings.google_client_secret.get_secret_value()
        self._redirect_uri = settings.redirect_uri
        self._transport = transport

    def authorization_url(self, state: str, nonce: str, *, consent: bool = False) -> str:
        """`access_type=offline` asks for a refresh token. Google only sends one on a consent
        screen, so `consent=True` forces that screen for a user calsync has no token for."""
        query = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "state": state,
            "nonce": nonce,
        }
        if consent:
            query["prompt"] = "consent"
        return f"{AUTH_URL}?{urlencode(query)}"

    async def exchange(self, code: str, nonce: str) -> Identity:
        tokens = await self._token_response(code)
        claims = _checked_claims(_id_token_claims(tokens), self._client_id, nonce)
        return Identity(
            email=str(claims["email"]).lower(),
            email_verified=claims.get("email_verified") is True,
            refresh_token=tokens.get("refresh_token"),
        )

    async def _token_response(self, code: str) -> dict[str, Any]:
        form = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S) as client:
            try:
                response = await client.post(TOKEN_URL, data=form)
            except httpx.HTTPError as err:
                raise OAuthError(f"couldn't reach Google: {err}") from None
        if response.status_code != 200:
            raise OAuthError(f"Google rejected the sign-in code ({response.status_code})")
        return response.json()


def _id_token_claims(tokens: dict[str, Any]) -> dict[str, Any]:
    """The ID token's payload, without checking its signature.

    The token came straight from Google's token endpoint over TLS, which OpenID
    Connect Core 3.1.3.7 accepts in place of signature validation.
    """
    try:
        payload = str(tokens["id_token"]).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (KeyError, IndexError, ValueError, binascii.Error):
        raise OAuthError("Google sent no readable ID token") from None


def _checked_claims(claims: dict[str, Any], client_id: str, nonce: str) -> dict[str, Any]:
    problems = {
        "issuer": claims.get("iss") in ISSUERS,
        "audience": claims.get("aud") == client_id,
        "nonce": claims.get("nonce") == nonce,
        "expiry": float(claims.get("exp", 0)) > time.time(),
        "email": bool(claims.get("email")),
    }
    failed = [name for name, ok in problems.items() if not ok]
    if failed:
        raise OAuthError(f"ID token failed checks: {', '.join(failed)}")
    return claims
