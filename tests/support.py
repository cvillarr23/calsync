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
