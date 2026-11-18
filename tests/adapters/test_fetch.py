import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.fetch import (
    DEFAULT_USER_AGENT,
    AddressGuard,
    BlockedAddress,
    FetchLimits,
    FetchSession,
    FetchTimeout,
    PageCache,
    PageLimitExceeded,
    ResponseTooLarge,
    resolve,
)
from app.settings import load_settings

pytestmark = pytest.mark.anyio

TEST_HOST = "calsync-test.invalid"


class Handler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        getattr(self, "route_" + url.path.strip("/").replace("-", "_"))(query)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.reply(200, body)

    def route_echo(self, query):
        headers = {"ua": self.headers["User-Agent"], "cookie": self.headers["Cookie"]}
        self.reply(200, json.dumps(headers).encode())

    def route_set_cookie(self, query):
        self.reply(200, b"ok", {"Set-Cookie": "session=abc; Path=/"})

    def route_redirect(self, query):
        self.reply(302, b"", {"Location": query["to"]})

    def route_slow(self, query):
        time.sleep(float(query["s"]))
        self.reply(200, b"late")

    def route_big(self, query):
        self.reply(200, b"x" * int(query["n"]))

    def route_unsized(self, query):
        """Close-delimited body with no Content-Length, so only streaming can cap it."""
        self.send_response(200)
        self.end_headers()
        for _ in range(int(query["n"]) // 1024):
            self.wfile.write(b"x" * 1024)

    def route_count(self, query):
        Handler.hits += 1
        self.reply(200, f"hit {Handler.hits}".encode())

    def reply(self, status, body, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://{TEST_HOST}:{httpd.server_address[1]}"
    httpd.shutdown()


class AllowTestHost(AddressGuard):
    """Lets the local test server through by name; every other host gets the real guard."""

    def is_allowed(self, host, ip):
        return host == TEST_HOST or super().is_allowed(host, ip)


async def fake_resolver(host, port):
    if host == TEST_HOST:
        return ["127.0.0.1"]
    if host == "rebind.example":
        return ["93.184.215.14", "10.0.0.5"]
    return await resolve(host, port)


def session(limits=None, **kwargs):
    kwargs.setdefault("guard", AllowTestHost())
    return FetchSession(limits or FetchLimits(), resolver=fake_resolver, **kwargs)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://rebind.example/",
    ],
)
async def test_guard_blocks_non_public_addresses(url):
    async with session() as s:
        with pytest.raises(BlockedAddress):
            await s.fetch(url)


@pytest.mark.parametrize(
    "target",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
async def test_guard_blocks_redirects_to_non_public_addresses(server, target):
    async with session() as s:
        with pytest.raises(BlockedAddress):
            await s.fetch(f"{server}/redirect?to={target}")


async def test_guard_checks_at_connect_time(monkeypatch):
    """A name that resolved publicly while parsing but privately at connect is still blocked."""
    calls = []

    async def flipping_resolver(host, port):
        calls.append(host)
        return ["10.0.0.7"]

    async with FetchSession(FetchLimits(), resolver=flipping_resolver) as s:
        with pytest.raises(BlockedAddress, match="10.0.0.7"):
            await s.fetch("https://public.example/")
    assert calls == ["public.example"]


async def test_allow_private_lets_local_addresses_through(server):
    port = server.rsplit(":", 1)[1]
    async with FetchSession(FetchLimits(allow_private=True)) as s:
        page = await s.fetch(f"http://127.0.0.1:{port}/big?n=3")
    assert page.content == b"xxx"


def test_limits_from_settings(required_env):
    required_env.setenv("CALSYNC_FETCH_ALLOW_PRIVATE", "true")
    required_env.setenv("CALSYNC_FETCH_MAX_PAGES", "5")
    limits = FetchLimits.from_settings(load_settings())
    assert limits == FetchLimits(
        timeout_s=15, max_pages=5, max_bytes=2 * 1024**2, allow_private=True
    )


async def test_run_timeout(server):
    async with session(FetchLimits(timeout_s=0.3)) as s:
        started = time.monotonic()
        with pytest.raises(FetchTimeout):
            await s.fetch(f"{server}/slow?s=2")
    assert time.monotonic() - started < 1.5


async def test_timeout_is_shared_across_the_run(server):
    async with session(FetchLimits(timeout_s=0.5)) as s:
        await s.fetch(f"{server}/slow?s=0.3")
        with pytest.raises(FetchTimeout):
            await s.fetch(f"{server}/slow?s=0.3")


async def test_declared_size_over_cap(server):
    async with session(FetchLimits(max_bytes=1000)) as s:
        with pytest.raises(ResponseTooLarge):
            await s.fetch(f"{server}/big?n=1001")


async def test_streamed_size_over_cap(server):
    async with session(FetchLimits(max_bytes=10_000)) as s:
        with pytest.raises(ResponseTooLarge):
            await s.fetch(f"{server}/unsized?n=50000")


async def test_byte_cap_is_shared_across_the_run(server):
    async with session(FetchLimits(max_bytes=1000)) as s:
        await s.fetch(f"{server}/big?n=600")
        with pytest.raises(ResponseTooLarge):
            await s.fetch(f"{server}/big?n=600")


async def test_page_limit_counts_redirect_hops(server):
    async with session(FetchLimits(max_pages=2)) as s:
        await s.fetch(f"{server}/redirect?to=/big?n=1")
        with pytest.raises(PageLimitExceeded):
            await s.fetch(f"{server}/big?n=1")


async def test_cookie_jar_and_default_user_agent(server):
    async with session() as s:
        await s.fetch(f"{server}/set-cookie")
        echoed = json.loads((await s.fetch(f"{server}/echo")).text)
    assert echoed == {"ua": DEFAULT_USER_AGENT, "cookie": "session=abc"}


async def test_user_agent_override(server):
    async with session(user_agent="Mozilla/5.0 test") as s:
        echoed = json.loads((await s.fetch(f"{server}/echo")).text)
    assert echoed["ua"] == "Mozilla/5.0 test"


async def test_follow_redirects_flag(server):
    async with session() as s:
        hop = await s.fetch(f"{server}/redirect?to=/big?n=2", follow_redirects=False)
        landed = await s.fetch(f"{server}/redirect?to=/big?n=2")
    assert (hop.status_code, hop.headers["location"]) == (302, "/big?n=2")
    assert (landed.status_code, landed.content) == (200, b"xx")
    assert landed.url == f"{server}/big?n=2"


async def test_post_json(server):
    async with session() as s:
        page = await s.fetch(f"{server}/echo", method="POST", json={"a": 1})
    assert json.loads(page.text) == {"a": 1}


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def test_preview_cache_hits_within_ttl(server):
    clock = FakeClock()
    cache = PageCache(ttl_s=300, clock=clock)
    async with session(FetchLimits(max_pages=2), cache=cache) as s:
        first = (await s.fetch(f"{server}/count")).text
        clock.now = 299
        assert (await s.fetch(f"{server}/count")).text == first
        clock.now = 301
        assert (await s.fetch(f"{server}/count")).text != first


def test_cache_evicts_oldest():
    cache = PageCache(max_entries=2)
    page = object()
    for n in range(3):
        cache.put(("GET", f"u{n}", b""), page)
    assert cache.get(("GET", "u0", b"")) is None
    assert cache.get(("GET", "u2", b"")) is page
