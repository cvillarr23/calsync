"""`/auth`: Google sign-in, the callback, and sign-out."""

import secrets

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.csrf import require_csrf
from app.api.deps import SESSION_USER, AppSettings, Google
from app.db.session import Db
from app.services.auth import Identity, OAuthError, is_allowed
from app.services.users import needs_consent, sign_in
from app.web.rendering import render

router = APIRouter(prefix="/auth")

PENDING = "oauth"
"""Session key for the state, nonce and consent flag of a sign-in in progress."""


@router.get("/login")
def login(request: Request, google: Google, consent: bool = False) -> RedirectResponse:
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session[PENDING] = {"state": state, "nonce": nonce, "consent": consent}
    url = google.authorization_url(state, nonce, consent=consent)
    return RedirectResponse(url, status.HTTP_303_SEE_OTHER)


@router.get("/callback")
async def callback(
    request: Request,
    db: Db,
    google: Google,
    settings: AppSettings,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    pending = request.session.pop(PENDING, None)
    if error:
        return _problem(request, f"Google didn't complete the sign-in ({error}).")
    if not _state_matches(pending, state) or not code:
        return _problem(request, "This sign-in link expired or was already used.")
    try:
        identity = await google.exchange(code, pending["nonce"])
    except OAuthError as err:
        return _problem(request, str(err))
    if not is_allowed(settings, identity):
        return _denied(request, identity)
    if needs_consent(db, identity) and not pending.get("consent"):
        return RedirectResponse("/auth/login?consent=true", status.HTTP_303_SEE_OTHER)
    return _signed_in(request, db, identity, settings)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth/signed-out", status.HTTP_303_SEE_OTHER)


@router.get("/signed-out")
def signed_out(request: Request) -> HTMLResponse:
    return render(request, "auth/signed_out.html")


def _state_matches(pending: object, state: str | None) -> bool:
    return isinstance(pending, dict) and bool(state) and pending.get("state") == state


def _signed_in(request: Request, db: Db, identity: Identity, settings: AppSettings) -> Response:
    """A fresh session on sign-in, so nothing from before it (CSRF token included) carries over."""
    user = sign_in(db, identity, settings)
    request.session.clear()
    request.session[SESSION_USER] = user.id
    return RedirectResponse("/", status.HTTP_303_SEE_OTHER)


def _denied(request: Request, identity: Identity) -> HTMLResponse:
    request.session.clear()
    context = {"email": identity.email, "verified": identity.email_verified}
    return render(request, "auth/denied.html", context, status_code=status.HTTP_403_FORBIDDEN)


def _problem(request: Request, message: str) -> HTMLResponse:
    context = {"message": message}
    return render(request, "auth/problem.html", context, status_code=status.HTTP_400_BAD_REQUEST)
