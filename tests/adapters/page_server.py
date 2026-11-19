"""A local HTTP server for adapter tests, reached through a fake test host name.

The SSRF guard blocks loopback, so tests reach this server as `calsync-test.invalid`.
A guard that allows only that name and a resolver that maps it to 127.0.0.1 let it
through, and every other host still meets the real guard.
"""

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.adapters.fetch import AddressGuard, resolve

TEST_HOST = "calsync-test.invalid"
PAGES = Path(__file__).parent / "pages"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json"}


class AllowTestHost(AddressGuard):
    def is_allowed(self, host, ip):
        return host == TEST_HOST or super().is_allowed(host, ip)


async def fake_resolver(host, port):
    if host == TEST_HOST:
        return ["127.0.0.1"]
    return await resolve(host, port)


class PageHandler(BaseHTTPRequestHandler):
    """Serves files from `pages/`; the query string is recorded and ignored."""

    requests: list[str] = []

    def do_GET(self):
        PageHandler.requests.append(self.path)
        path = PAGES / urlsplit(self.path).path.lstrip("/")
        if not path.is_file():
            self.reply(404, b"not found", "text/plain")
            return
        self.reply(200, path.read_bytes(), TYPES.get(path.suffix, "text/plain"))

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextmanager
def serve_pages():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), PageHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://{TEST_HOST}:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
