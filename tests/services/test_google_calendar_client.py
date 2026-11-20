from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.db.models import GoogleMap
from app.services.google_calendar import (
    CalendarApiError,
    GoogleConnection,
    GoogleReconnectNeeded,
)
from app.services.sync.google_plan import plan_push
from app.services.tokens import encrypt_token
from tests.support import FakeCalendar

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)


@pytest.fixture
def settings():
    return SimpleNamespace(
        google_client_id="placeholder-client-id",
        google_client_secret=SecretStr("placeholder-client-secret"),
        token_enc_key=SecretStr(Fernet.generate_key().decode()),
    )


@pytest.fixture
def calendar():
    return FakeCalendar()


@pytest.fixture
def user(settings):
    return SimpleNamespace(id=1, refresh_token_enc=encrypt_token(settings, "refresh-1"))


def connect(settings, transport, sleeps=None):
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return GoogleConnection(settings, transport, sleep)


async def test_lists_writable_calendars_primary_first(settings, calendar, user):
    calendars = await connect(settings, calendar.transport).calendars(user)
    assert [(c.summary, c.primary) for c in calendars] == [("Me", True), ("Skating", False)]


async def test_retry_after_is_honoured(settings, calendar, user):
    sleeps = []
    calendar.failures = [(429, {"Retry-After": "3"})]
    await connect(settings, calendar.transport, sleeps).calendars(user)
    assert sleeps == [3.0]


async def test_forbidden_with_a_rate_limit_reason_is_retried(settings, user):
    answers = [
        httpx.Response(403, json={"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}),
        httpx.Response(200, json={"items": []}),
    ]
    transport = _scripted(answers)
    assert await connect(settings, transport).calendars(user) == []


async def test_plain_forbidden_is_not_retried(settings, user):
    answers = [httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}})]
    with pytest.raises(CalendarApiError, match="403 \\(forbidden\\)"):
        await connect(settings, _scripted(answers)).calendars(user)


async def test_unauthorized_refreshes_once_then_asks_for_reconnect(settings, user):
    answers = [httpx.Response(401), httpx.Response(401)]
    with pytest.raises(GoogleReconnectNeeded):
        await connect(settings, _scripted(answers)).calendars(user)


async def test_unreachable_google_fails_after_the_retries(settings, user):
    def refuse(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "access-1", "expires_in": 3600})
        raise httpx.ConnectError("connection refused")

    with pytest.raises(CalendarApiError, match="couldn't reach Google"):
        await connect(settings, httpx.MockTransport(refuse)).calendars(user)


async def test_token_sealed_with_another_key_asks_for_reconnect(settings, calendar):
    other = SimpleNamespace(token_enc_key=SecretStr(Fernet.generate_key().decode()))
    user = SimpleNamespace(id=1, refresh_token_enc=encrypt_token(other, "refresh-1"))
    with pytest.raises(GoogleReconnectNeeded):
        await connect(settings, calendar.transport).calendars(user)


def test_rows_without_a_start_or_calendar_are_forgotten_not_deleted():
    legacy = GoogleMap(uid="a", google_event_id="g1", content_hash="h", calendar_id=None)
    undated = GoogleMap(uid="b", google_event_id="g2", content_hash="h", calendar_id="c")
    plan = plan_push("c", {"a": legacy, "b": undated}, [], NOW)
    assert (plan.deletes, plan.forget) == ([], [legacy, undated])
    assert not plan.calls_google


def _scripted(answers):
    """Answers calendar requests in order; the token endpoint always succeeds."""
    queue = list(answers)

    def handle(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "access-1", "expires_in": 3600})
        return queue.pop(0)

    return httpx.MockTransport(handle)
