"""Static HTTP fetching for adapter runs: SSRF guard, per-run limits and a preview cache.

The guard runs where connections are opened, not where URLs are parsed. Every
address a host resolves to is checked, the socket connects to the address that
was checked (so DNS rebinding can't swap it), and each redirect hop opens its
own guarded connection.
"""

import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import anyio
import httpcore
import httpx

from app.settings import Settings

DEFAULT_USER_AGENT = "calsync/0.1 (+https://github.com/cvillarr23/calsync)"

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]
CacheKey = tuple[str, str, bytes]


class FetchError(RuntimeError):
    """A fetch failed or broke one of the run's limits."""


class BlockedAddress(FetchError):
    """The target resolves to a private, loopback, link-local or otherwise non-public address."""


class FetchTimeout(FetchError):
    """The run's time limit ran out."""


class PageLimitExceeded(FetchError):
    """The run made more requests than it may."""


class ResponseTooLarge(FetchError):
    """The run downloaded more bytes than it may."""


@dataclass(frozen=True)
class FetchLimits:
    """Per-run budget; one adapter run shares one budget across all its requests."""

    timeout_s: float = 15.0
    max_pages: int = 20
    max_bytes: int = 2 * 1024 * 1024
    allow_private: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "FetchLimits":
        return cls(
            timeout_s=settings.fetch_timeout_s,
            max_pages=settings.fetch_max_pages,
            max_bytes=settings.fetch_max_bytes,
            allow_private=settings.fetch_allow_private,
        )


class AddressGuard:
    """Decides which resolved addresses a fetch may connect to."""

    def __init__(self, allow_private: bool = False) -> None:
        self.allow_private = allow_private

    def is_allowed(self, host: str, ip: IPAddress) -> bool:
        """Only globally routable unicast addresses, unless private fetching is allowed.

        `is_global` is false for private, loopback, link-local (including cloud
        metadata at 169.254.169.254), CGNAT, unspecified and reserved ranges.
        """
        if self.allow_private:
            return True
        ip = _unmapped(ip)
        return ip.is_global and not ip.is_multicast


def _unmapped(ip: IPAddress) -> IPAddress:
    """`::ffff:127.0.0.1` is judged as `127.0.0.1`."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


async def resolve(host: str, port: int) -> list[str]:
    """All addresses for a host, in resolver order, without duplicates."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as err:
        raise FetchError(f"can't resolve {host}: {err.strerror}") from None
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Resolves and vets the host itself, then connects to the vetted address."""

    def __init__(self, guard: AddressGuard, resolver: Resolver) -> None:
        self._guard = guard
        self._resolver = resolver
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        address = await self._vetted_address(host, port)
        return await self._inner.connect_tcp(address, port, timeout, local_address, socket_options)

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise BlockedAddress("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)

    async def _vetted_address(self, host: str, port: int) -> str:
        """The first address, provided every address the host resolves to is allowed."""
        addresses = await self._resolver(host, port)
        if not addresses:
            raise FetchError(f"can't resolve {host}")
        for address in addresses:
            if not self._guard.is_allowed(host, ipaddress.ip_address(address)):
                raise BlockedAddress(f"{host} resolves to non-public address {address}")
        return addresses[0]


class _GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx's transport, with its connection pool rebuilt on the guarded backend.

    httpx has no public hook for the network backend, so this replaces `_pool`;
    the connect-time guard tests fail if a future httpx changes that.
    """

    def __init__(self, backend: httpcore.AsyncNetworkBackend) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            network_backend=backend,
        )


@dataclass(frozen=True)
class Page:
    url: str
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    encoding: str | None = None

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class PageCache:
    """Short-lived page cache for previews, so editing selectors doesn't hammer the site."""

    def __init__(
        self,
        ttl_s: float = 300.0,
        max_entries: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[CacheKey, tuple[float, Page]] = OrderedDict()

    def get(self, key: CacheKey) -> Page | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() - entry[0] > self._ttl_s:
            del self._entries[key]
            return None
        return entry[1]

    def put(self, key: CacheKey, page: Page) -> None:
        self._entries[key] = (self._clock(), page)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class FetchSession:
    """One adapter run's HTTP client: shared cookie jar, user agent and limits.

    Use as `async with FetchSession(limits) as session: await session.fetch(url)`.
    """

    def __init__(
        self,
        limits: FetchLimits,
        *,
        guard: AddressGuard | None = None,
        cache: PageCache | None = None,
        user_agent: str | None = None,
        resolver: Resolver = resolve,
    ) -> None:
        self._limits = limits
        self._cache = cache
        self._pages = 0
        self._bytes = 0
        self._deadline = 0.0
        backend = _GuardedBackend(guard or AddressGuard(limits.allow_private), resolver)
        self._client = httpx.AsyncClient(
            transport=_GuardedTransport(backend),
            headers={"User-Agent": user_agent or DEFAULT_USER_AGENT},
            timeout=limits.timeout_s,
            trust_env=False,
            event_hooks={"request": [self._count_request]},
        )

    async def __aenter__(self) -> "FetchSession":
        self._deadline = time.monotonic() + self._limits.timeout_s
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Page:
        """Fetch one page; cache hits skip the network and don't use the run's budget."""
        request = self._client.build_request(method, url, headers=headers, json=json, data=data)
        key = _cache_key(request)
        cached = self._cache.get(key) if self._cache else None
        if cached is not None:
            return cached
        page = await self._send_within_deadline(request, follow_redirects)
        if self._cache:
            self._cache.put(key, page)
        return page

    async def _count_request(self, request: httpx.Request) -> None:
        """Every request counts against the page limit, redirect hops included."""
        self._pages += 1
        if self._pages > self._limits.max_pages:
            raise PageLimitExceeded(f"run exceeded {self._limits.max_pages} requests")

    async def _send_within_deadline(self, request: httpx.Request, follow: bool) -> Page:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise self._timeout()
        try:
            with anyio.fail_after(remaining):
                return await self._send(request, follow)
        except (TimeoutError, httpx.TimeoutException):
            raise self._timeout() from None
        except httpx.HTTPError as err:
            raise FetchError(f"{request.method} {request.url}: {err}") from None

    async def _send(self, request: httpx.Request, follow: bool) -> Page:
        response = await self._client.send(request, stream=True, follow_redirects=follow)
        try:
            self._check_declared_size(response)
            content = await self._read_capped(response)
        finally:
            await response.aclose()
        return _page(response, content)

    def _check_declared_size(self, response: httpx.Response) -> None:
        """Fail before downloading when Content-Length already breaks the budget."""
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and self._bytes + int(declared) > self._limits.max_bytes:
            raise self._too_large()

    async def _read_capped(self, response: httpx.Response) -> bytes:
        """Read the decoded body, stopping as soon as the run's byte budget is spent."""
        chunks = []
        async for chunk in response.aiter_bytes():
            self._bytes += len(chunk)
            if self._bytes > self._limits.max_bytes:
                raise self._too_large()
            chunks.append(chunk)
        return b"".join(chunks)

    def _timeout(self) -> FetchTimeout:
        return FetchTimeout(f"run exceeded {self._limits.timeout_s:g}s")

    def _too_large(self) -> ResponseTooLarge:
        return ResponseTooLarge(f"run exceeded {self._limits.max_bytes} bytes")


def _cache_key(request: httpx.Request) -> CacheKey:
    return request.method, str(request.url), request.content


def _page(response: httpx.Response, content: bytes) -> Page:
    return Page(
        url=str(response.url),
        status_code=response.status_code,
        headers=dict(response.headers),
        content=content,
        encoding=response.charset_encoding,
    )
