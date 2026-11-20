import base64

import pytest

REQUIRED_ENV = {
    "CALSYNC_BASE_URL": "https://calsync.example",
    "GOOGLE_CLIENT_ID": "placeholder-client-id",
    "GOOGLE_CLIENT_SECRET": "placeholder-client-secret",
    "CALSYNC_SESSION_SECRET": "placeholder-session-secret",
    "CALSYNC_TOKEN_ENC_KEY": base64.urlsafe_b64encode(bytes(32)).decode(),
}


@pytest.fixture
def clean_env(monkeypatch):
    """Remove any CALSYNC_/GOOGLE_ variables inherited from the developer's shell."""
    import os

    for name in list(os.environ):
        if name.startswith(("CALSYNC_", "GOOGLE_")):
            monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def required_env(clean_env):
    for name, value in REQUIRED_ENV.items():
        clean_env.setenv(name, value)
    return clean_env


@pytest.fixture
def app_env(required_env, tmp_path):
    """Required variables plus a throwaway data directory for the database."""
    required_env.setenv("CALSYNC_DATA_DIR", str(tmp_path / "data"))
    return required_env


@pytest.fixture
def google():
    from tests.support import FakeGoogle

    return FakeGoogle()


@pytest.fixture
def anon_client(app_env, google):
    """A test client with the app's lifespan running and Google faked, not signed in.

    The base URL is https because the session cookie is Secure on https instances.
    The scheduler is paused: jobs exist, but no real sync starts behind a test's back.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.auth import GoogleOAuth
    from app.settings import load_settings

    settings = load_settings()
    app = create_app(settings, run_scheduler=False)
    app.state.google = GoogleOAuth(settings, transport=google.transport)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture
def client(anon_client, google):
    """Signed in as me@example.com, sending the session's CSRF token on every request."""
    from tests.support import google_sign_in, page_csrf_token

    response = google_sign_in(anon_client, google)
    assert response.status_code == 303, response.text
    anon_client.headers["X-CSRF-Token"] = page_csrf_token(anon_client)
    return anon_client


@pytest.fixture
def anyio_backend():
    return "asyncio"
