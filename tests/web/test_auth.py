import re
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.api.csrf import HEADER
from app.db.models import Source, User
from app.services.tokens import decrypt_token
from app.services.users import LOCAL_USER_EMAIL
from tests.support import google_sign_in, page_csrf_token


def db_session(client):
    return client.app.state.sessions()


def test_pages_redirect_to_sign_in(anon_client):
    response = anon_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_htmx_requests_get_hx_redirect(anon_client):
    response = anon_client.get("/sources/params", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/auth/login"


@pytest.mark.parametrize("path", ["/adapters/validate", "/adapters/test"])
def test_adapter_editor_posts_need_sign_in(anon_client, path):
    page = anon_client.get("/auth/signed-out")  # signed-out pages hand out a CSRF token too
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
    headers = {HEADER: token, "HX-Request": "true"}
    response = anon_client.post(path, data={"yaml": "id: x"}, headers=headers)
    assert response.status_code == 401


def test_api_needs_sign_in(anon_client):
    assert anon_client.get("/api/sources").status_code == 401


def test_login_redirects_to_google_with_offline_access(anon_client):
    response = anon_client.get("/auth/login", follow_redirects=False)
    url = urlsplit(response.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["redirect_uri"] == ["https://calsync.example/auth/callback"]
    assert query["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/calendar.events" in query["scope"][0].split()
    assert "prompt" not in query


def test_sign_in_stores_encrypted_refresh_token(anon_client, google):
    response = google_sign_in(anon_client, google)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert anon_client.get("/").status_code == 200
    with db_session(anon_client) as db:
        user = db.scalar(select(User).where(User.email == "me@example.com"))
        assert user.refresh_token_enc != "refresh-1"
        assert decrypt_token(anon_client.app.state.settings, user.refresh_token_enc) == "refresh-1"
    assert google.token_requests[0]["redirect_uri"] == "https://calsync.example/auth/callback"


def test_disallowed_email_is_rejected_after_callback(app_env, make_client, google):
    app_env.setenv("CALSYNC_ALLOWED_EMAILS", "friend@example.com")
    client = make_client()
    response = google_sign_in(client, google, email="stranger@example.com")
    assert response.status_code == 403
    assert "stranger@example.com" in response.text
    assert "CALSYNC_ALLOWED_EMAILS" in response.text
    assert client.get("/", follow_redirects=False).status_code == 303
    with db_session(client) as db:
        assert db.scalar(select(User).where(User.email == "stranger@example.com")) is None


def test_allowed_email_matches_case_insensitively(app_env, make_client, google):
    app_env.setenv("CALSYNC_ALLOWED_EMAILS", "Friend@Example.com")
    client = make_client()
    assert google_sign_in(client, google, email="FRIEND@example.com").status_code == 303


def test_unverified_email_is_rejected(anon_client, google):
    response = google_sign_in(anon_client, google, email_verified=False)
    assert response.status_code == 403
    assert "hasn't verified" in response.text


def test_state_mismatch_is_rejected(anon_client):
    anon_client.get("/auth/login", follow_redirects=False)
    response = anon_client.get("/auth/callback", params={"code": "c", "state": "forged"})
    assert response.status_code == 400
    assert "expired" in response.text


def test_wrong_nonce_is_rejected(anon_client, google):
    login = anon_client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    google.nonce = "someone-elses"
    response = anon_client.get("/auth/callback", params={"code": "c", "state": state})
    assert response.status_code == 400
    assert "nonce" in response.text


def test_google_error_is_shown(anon_client):
    anon_client.get("/auth/login", follow_redirects=False)
    response = anon_client.get("/auth/callback", params={"error": "access_denied"})
    assert response.status_code == 400
    assert "access_denied" in response.text


def test_missing_refresh_token_asks_for_consent_once(anon_client, google):
    google.refresh_token = None
    first = google_sign_in(anon_client, google)
    assert first.headers["location"] == "/auth/login?consent=true"
    second = google_sign_in(anon_client, google, login_url=first.headers["location"])
    assert second.headers["location"] == "/"


def test_consent_login_sets_prompt(anon_client):
    response = anon_client.get("/auth/login?consent=true", follow_redirects=False)
    assert parse_qs(urlsplit(response.headers["location"]).query)["prompt"] == ["consent"]


def test_returning_user_with_stored_token_skips_consent(anon_client, google):
    google_sign_in(anon_client, google)
    google.refresh_token = None
    assert google_sign_in(anon_client, google).headers["location"] == "/"


def test_first_sign_in_adopts_the_local_user(anon_client, google):
    with anon_client.app.state.sessions.begin() as db:
        local = User(email=LOCAL_USER_EMAIL)
        db.add(local)
        db.flush()
        db.add(Source(user_id=local.id, name="Old", adapter_id="x", feed_token="t"))
    google_sign_in(anon_client, google)
    with db_session(anon_client) as db:
        user = db.scalar(select(User).where(User.email == "me@example.com"))
        assert [s.name for s in db.scalars(select(Source).where(Source.user_id == user.id))] == [
            "Old"
        ]


def test_logout_clears_the_session(client):
    response = client.post("/auth/logout", follow_redirects=False)
    assert response.headers["location"] == "/auth/signed-out"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_sign_in_rotates_the_csrf_token(client, google):
    before = client.headers[HEADER]
    google_sign_in(client, google)
    assert page_csrf_token(client) != before
