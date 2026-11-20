"""Fakes and sample data shared by tests in several packages."""

PYTHON_DEF = {
    "id": "sneaky",
    "version": 1,
    "name": "Sneaky",
    "kind": "python",
    "entrypoint": "os:system",
}


class FakeRunner:
    def __init__(self, events=None, error=None):
        self.events = list(events or [])
        self.error = error
        self.calls = []

    async def __call__(self, definition, params, window_start, window_end):
        self.calls.append((definition.id, dict(params), window_start, window_end))
        if self.error:
            raise self.error
        return list(self.events)


class RecordingTarget:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def apply(self, db, source, matched, now):
        self.calls.append([event.uid for event in matched])
        if self.error:
            raise self.error


class GatedRunner(FakeRunner):
    """A runner that holds each run open until `release` is set, to test overlapping runs."""

    def __init__(self, events=None):
        import anyio

        super().__init__(events)
        self.started = anyio.Event()
        self.release = anyio.Event()

    async def __call__(self, definition, params, window_start, window_end):
        self.calls.append((definition.id, dict(params), window_start, window_end))
        self.started.set()
        await self.release.wait()
        return list(self.events)


class FakeGoogle:
    """Stands in for Google's token endpoint, issuing ID tokens for `claims`.

    `sign_in` reads the nonce from the redirect `/auth/login` gives, as the real
    Google would echo it back in the ID token.
    """

    def __init__(self, client_id="placeholder-client-id"):
        self.client_id = client_id
        self.claims = {"email": "me@example.com", "email_verified": True}
        self.refresh_token = "refresh-1"
        self.nonce = None
        self.status = 200
        self.token_requests = []

    @property
    def transport(self):
        import httpx

        return httpx.MockTransport(self._handle)

    def _handle(self, request):
        import httpx

        self.token_requests.append(dict(httpx.QueryParams(request.content.decode())))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_grant"})
        body = {"access_token": "access-1", "id_token": self.id_token()}
        if self.refresh_token:
            body["refresh_token"] = self.refresh_token
        return httpx.Response(200, json=body)

    def id_token(self, **overrides):
        import base64
        import json
        import time

        claims = {
            "iss": "https://accounts.google.com",
            "aud": self.client_id,
            "exp": time.time() + 600,
            "nonce": self.nonce,
            **self.claims,
            **overrides,
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"e30.{payload}.c2ln"


def google_sign_in(client, google, *, login_url="/auth/login", **claims):
    """Run `/auth/login` → Google → `/auth/callback`; returns the callback's response."""
    from urllib.parse import parse_qs, urlsplit

    login = client.get(login_url, follow_redirects=False)
    query = parse_qs(urlsplit(login.headers["location"]).query)
    google.nonce = query["nonce"][0]
    google.claims.update(claims)
    params = {"code": "code-1", "state": query["state"][0]}
    return client.get("/auth/callback", params=params, follow_redirects=False)


def page_csrf_token(client):
    """The CSRF token the signed-in pages embed in `<meta name="csrf-token">`."""
    import re

    page = client.get("/")
    return re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)


async def no_sleep(seconds):
    """Stands in for `asyncio.sleep` so backoff waits don't slow the tests."""


class FakeCalendar:
    """Stands in for Google's token endpoint (refresh grants) and the Calendar v3 API.

    `writes` records each insert, patch and delete; `failures` holds `(status, headers)`
    answers for the next Calendar requests. Events live in `events[calendar][event_id]`.
    """

    def __init__(self):
        self.calendars = [
            {"id": "primary@example.com", "summary": "Me", "primary": True},
            {"id": "skate#rink@group.calendar.google.com", "summary": "Skating"},
        ]
        self.events = {calendar["id"]: {} for calendar in self.calendars}
        self.writes = []
        self.reads = []
        self.failures = []
        self.grant_revoked = False
        self.refreshes = 0
        self._ids = 0

    @property
    def transport(self):
        import httpx

        return httpx.MockTransport(self._handle)

    def tagged(self, calendar_id):
        """The calendar's events that carry a calsync tag, keyed by calsync uid."""
        return {
            body["extendedProperties"]["private"]["calsync_uid"]: body
            for body in self.events[calendar_id].values()
            if "calsync_uid" in body.get("extendedProperties", {}).get("private", {})
        }

    def add_event(self, calendar_id, **body):
        """An event someone made in Google directly; returns its id."""
        self._ids += 1
        event_id = f"own-{self._ids}"
        self.events[calendar_id][event_id] = {"id": event_id, **body}
        return event_id

    def _handle(self, request):
        import httpx

        if request.url.host == "oauth2.googleapis.com":
            return self._token(request)
        if self.failures:
            status, headers = self.failures.pop(0)
            return httpx.Response(status, headers=headers, json={"error": {"code": status}})
        return self._calendar_api(request)

    def _token(self, request):
        import httpx

        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["grant_type"] == "refresh_token"
        if self.grant_revoked:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.refreshes += 1
        return httpx.Response(
            200, json={"access_token": f"access-{self.refreshes}", "expires_in": 3600}
        )

    def _calendar_api(self, request):
        import json
        from urllib.parse import unquote

        import httpx

        assert request.headers["Authorization"].startswith("Bearer access-")
        path = request.url.raw_path.decode().split("?")[0].removeprefix("/calendar/v3")
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if parts == ["users", "me", "calendarList"]:
            return httpx.Response(200, json={"items": self.calendars})
        calendar_id, event_id = parts[1], (parts[3] if len(parts) > 3 else None)
        if calendar_id not in self.events:
            return httpx.Response(404, json={"error": {"code": 404}})
        events = self.events[calendar_id]
        body = json.loads(request.content) if request.content else None
        if request.method == "GET":
            self.reads.append((calendar_id, event_id))
        else:
            self.writes.append((request.method, calendar_id, event_id))
        if request.method == "POST":
            self._ids += 1
            new_id = f"evt-{self._ids}"
            events[new_id] = {**body, "id": new_id}
            return httpx.Response(200, json=events[new_id])
        if event_id not in events:
            return httpx.Response(404, json={"error": {"code": 404}})
        if request.method == "GET":
            return httpx.Response(200, json=events[event_id])
        if request.method == "PATCH":
            events[event_id] = {**events[event_id], **body}
            return httpx.Response(200, json=events[event_id])
        del events[event_id]
        return httpx.Response(204)
