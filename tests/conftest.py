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
def client(app_env):
    """A test client with the app's lifespan running, so the database is open."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import load_settings

    with TestClient(create_app(load_settings())) as test_client:
        yield test_client


@pytest.fixture
def anyio_backend():
    return "asyncio"
