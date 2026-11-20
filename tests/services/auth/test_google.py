import pytest

from app.services.auth import GoogleOAuth, Identity, OAuthError, is_allowed
from app.settings import load_settings
from tests.support import FakeGoogle

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(required_env):
    return load_settings()


@pytest.fixture
def google():
    fake = FakeGoogle()
    fake.nonce = "n-1"
    return fake


async def test_exchange_returns_the_identity(settings, google):
    oauth = GoogleOAuth(settings, transport=google.transport)
    identity = await oauth.exchange("code", "n-1")
    assert identity == Identity("me@example.com", True, "refresh-1")
    assert google.token_requests[0]["grant_type"] == "authorization_code"


@pytest.mark.parametrize(
    "overrides, failed",
    [
        ({"aud": "someone-else"}, "audience"),
        ({"iss": "https://evil.example"}, "issuer"),
        ({"exp": 1}, "expiry"),
        ({"nonce": "other"}, "nonce"),
    ],
)
async def test_bad_id_tokens_are_rejected(settings, google, overrides, failed):
    google.claims.update(overrides)
    with pytest.raises(OAuthError, match=failed):
        await GoogleOAuth(settings, transport=google.transport).exchange("code", "n-1")


async def test_rejected_code(settings, google):
    google.status = 400
    with pytest.raises(OAuthError, match="rejected"):
        await GoogleOAuth(settings, transport=google.transport).exchange("code", "n-1")


def test_redirect_uri_is_joined_without_double_slash(settings):
    url = GoogleOAuth(settings).authorization_url("s", "n")
    assert "redirect_uri=https%3A%2F%2Fcalsync.example%2Fauth%2Fcallback&" in url


@pytest.mark.parametrize(
    "allowed, identity, ok",
    [
        ("", Identity("a@example.com", True), True),
        ("", Identity("a@example.com", False), False),
        ("b@example.com", Identity("a@example.com", True), False),
        ("A@example.com, b@example.com", Identity("a@example.com", True), True),
    ],
)
def test_allowlist(required_env, allowed, identity, ok):
    required_env.setenv("CALSYNC_ALLOWED_EMAILS", allowed)
    assert is_allowed(load_settings(), identity) is ok
