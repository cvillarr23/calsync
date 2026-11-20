"""CSRF protection for every state-changing request, from pages and the API alike.

A signed-in session cookie is enough to call the API, and the API accepts any
content type, so a cross-site form could otherwise post to it. Each session
gets a random token; unsafe requests must echo it in the `X-CSRF-Token` header
(htmx and scripts) or a `csrf_token` form field (plain forms).
"""

import hmac
import secrets

from fastapi import HTTPException, Request, status

SESSION_KEY = "csrf_token"
HEADER = "X-CSRF-Token"
FORM_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token(request: Request) -> str:
    """This session's token, created on first use."""
    token = request.session.get(SESSION_KEY)
    if not token:
        token = request.session[SESSION_KEY] = secrets.token_urlsafe(32)
    return token


async def require_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    expected = request.session.get(SESSION_KEY)
    sent = request.headers.get(HEADER) or await _form_token(request)
    if not expected or not sent or not hmac.compare_digest(str(sent), expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or invalid CSRF token")


async def _form_token(request: Request) -> str | None:
    """Only form bodies are parsed; anything else must use the header."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        return None
    value = (await request.form()).get(FORM_FIELD)
    return value if isinstance(value, str) else None
