"""A fake two-step calendar API for pipeline tests.

`GET /calendar` answers with a redirect to an error page, but its own body embeds
`app.config = {...};` and sets a session cookie, so a definition has to read it
with `follow_redirects: false`. `POST /api/events` wants that cookie plus
`{"date": "YYYY-MM-DD HH:MM:SS", "config": <the object>}` and returns
`{"d": "<json string>"}` with the bookings in the 14 days from `date`.
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.adapters.fetch import AddressGuard, FetchLimits, FetchSession, resolve

TEST_HOST = "calsync-test.invalid"
DEFINITION = Path(__file__).parent / "fixtures" / "two_step.yaml"
CONFIG = {"roomId": 7, "token": "abc=="}
SESSION_COOKIE = "sid=s3cret"
PAGE_DAYS = 14

BOOKINGS = [
    {
        "Name": "Public Skate   ",
        "StartUtc": "2026-12-02T18:00:00",
        "EndUtc": "2026-12-02T19:30:00",
        "Room": "Main Rink",
        "Status": 1,
    },
    {
        "Name": "Stick & Puck ",
        "StartUtc": "2026-12-09T12:00:00",
        "EndUtc": "2026-12-09T13:00:00",
        "Room": "Main Rink",
        "Status": 1,
    },
    {
        "Name": "Public Skate",
        "StartUtc": "2026-12-10T18:00:00",
        "EndUtc": "2026-12-10T19:30:00",
        "Room": "Main Rink",
        "Status": -12,
    },
    {
        "Name": "Figure Skating",
        "StartUtc": "2026-12-16T07:00:00",
        "EndUtc": "2026-12-16T08:00:00",
        "Room": "Studio Rink",
        "Status": 1,
    },
    {
        "Name": "Learn to Skate",
        "StartUtc": "2027-01-05T10:00:00",
        "EndUtc": "2027-01-05T11:00:00",
        "Room": "Studio Rink",
        "Status": 1,
    },
]

CALENDAR_PAGE = f"""<html><body><h1>Rink calendar</h1>
<script>app.config = {json.dumps(CONFIG)};</script>
</body></html>""".encode()


class FakeApi(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/calendar":
            self.reply(302, CALENDAR_PAGE, {"Location": "/error", "Set-Cookie": SESSION_COOKIE})
        elif path == "/error":
            self.reply(200, b"<p>Something went wrong.</p>")
        else:
            self.reply(404, b"not found")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if urlsplit(self.path).path != "/api/events":
            self.reply(500, b"server error")
        elif SESSION_COOKIE not in (self.headers["Cookie"] or ""):
            self.reply(403, b"no session")
        else:
            self.events(json.loads(body))

    def events(self, request):
        if request.get("config") != CONFIG:
            self.reply(400, b"config must be sent back unchanged")
            return
        start = datetime.strptime(request["date"], "%Y-%m-%d %H:%M:%S")
        inner = {"Bookings": _bookings_between(start, start + timedelta(days=PAGE_DAYS))}
        self.reply(200, json.dumps({"d": json.dumps(inner)}).encode())

    def reply(self, status, body, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _bookings_between(start, end):
    return [b for b in BOOKINGS if start <= datetime.fromisoformat(b["StartUtc"]) < end]


def serve():
    """Start the fake API on a free port; returns the server and its base URL as TEST_HOST."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://{TEST_HOST}:{httpd.server_address[1]}"


class AllowTestHost(AddressGuard):
    """Lets the local fake API through by name; every other host gets the real guard."""

    def is_allowed(self, host, ip):
        return host == TEST_HOST or super().is_allowed(host, ip)


async def fake_resolver(host, port):
    return ["127.0.0.1"] if host == TEST_HOST else await resolve(host, port)


def fetch_session():
    return FetchSession(FetchLimits(), guard=AllowTestHost(), resolver=fake_resolver)
