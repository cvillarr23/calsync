"""Headless Chromium for `fetch.mode: headless`: render pages, then hand back their HTML.

Chromium never touches the network itself. Every request it makes, subresources
and frames included, is intercepted and answered through the run's guarded
`FetchSession`. The same SSRF guard, redirect checks, page, byte and time budget
and preview cache apply as in static mode. As a backstop, the browser is launched
with a proxy that points at a closed port, service workers are blocked and
WebSockets are refused, so a request that slipped past the interception would
fail instead of connecting.

The browser is launched once per run and always closed.
"""

from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import anyio
from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.adapters.fetch import (
    FetchError,
    FetchSession,
    FetchTimeout,
    PageLimitExceeded,
    ResponseTooLarge,
)
from app.adapters.html.page import HtmlPage

DEAD_PROXY = "http://127.0.0.1:9"
"""The discard port: nothing listens, so a request that escaped interception fails."""

FETCHED_RESOURCES = {"document", "script", "xhr", "fetch"}
"""Resource types worth a request; images, styles, fonts and media can't add events."""

_HOP_BY_HOP = {"content-encoding", "content-length", "transfer-encoding", "connection"}
_NOT_FORWARDED = {"cookie", "user-agent", "host", "content-length", "accept-encoding", "connection"}
_BUDGET_ERRORS = (FetchTimeout, PageLimitExceeded, ResponseTooLarge)
_CLOSE_GRACE_S = 10.0


class HeadlessUnavailable(FetchError):
    """Playwright's Chromium isn't installed or won't start."""


class _Interceptor:
    """Answers the browser's requests through the run's guarded session.

    A blocked subresource is aborted and the page carries on. A blocked main
    document, or any request that breaks the run's budget, fails the run.
    """

    def __init__(self, session: FetchSession) -> None:
        self._session = session
        self.fatal: FetchError | None = None
        self.failed = anyio.Event()

    async def handle(self, route: Route, request: Request) -> None:
        if not _wanted(request) or self.fatal is not None:
            await route.abort("blockedbyclient")
            return
        try:
            page = await self._session.fetch(
                request.url,
                method=request.method,
                headers=_forwarded(request.headers),
                content=request.post_data_buffer,
            )
        except FetchError as err:
            self._note_failure(request, err)
            await route.abort("blockedbyclient")
            return
        await route.fulfill(
            status=page.status_code, headers=_response_headers(page.headers), body=page.content
        )

    def raise_fatal(self) -> None:
        if self.fatal is not None:
            raise self.fatal

    def _note_failure(self, request: Request, err: FetchError) -> None:
        if isinstance(err, _BUDGET_ERRORS) or _is_main_document(request):
            self.fatal = self.fatal or err
            self.failed.set()


def _wanted(request: Request) -> bool:
    scheme = urlsplit(request.url).scheme
    return scheme in ("http", "https") and request.resource_type in FETCHED_RESOURCES


def _is_main_document(request: Request) -> bool:
    return request.is_navigation_request() and request.frame.parent_frame is None


def _forwarded(headers: dict[str, str]) -> dict[str, str]:
    """The browser's headers, minus the ones the session owns (cookies, user agent)."""
    return {name: value for name, value in headers.items() if name.lower() not in _NOT_FORWARDED}


def _response_headers(headers: dict[str, str]) -> dict[str, str]:
    """The session already decoded the body, so its encoding and length headers no longer hold."""
    return {name: value for name, value in headers.items() if name.lower() not in _HOP_BY_HOP}


async def _refuse_socket(socket: WebSocketRoute) -> None:
    await socket.close(code=1008, reason="calsync does not allow WebSockets")


class HeadlessBrowser:
    """One run's browser context; every call shares the run's interceptor and budget."""

    def __init__(self, context: BrowserContext, interceptor: _Interceptor) -> None:
        self._context = context
        self._interceptor = interceptor

    async def render(self, url: str, wait_for: str | None) -> HtmlPage:
        """Load a page, let its scripts build the DOM, and return the HTML."""
        page = await self._context.new_page()
        try:
            await self._open(page, url, wait_for)
            return HtmlPage(url=url, html=await page.content())
        finally:
            await page.close()

    async def click_through(
        self, url: str, wait_for: str | None, next_selector: str, max_pages: int
    ) -> list[HtmlPage]:
        """The first page and up to `max_pages - 1` more, clicking the next button between them.

        Stops early when the button is gone or disabled.
        """
        page = await self._context.new_page()
        try:
            await self._open(page, url, wait_for)
            pages = [HtmlPage(url=url, html=await page.content())]
            while len(pages) < max_pages and await self._click_next(page, next_selector):
                await self._settle(page, wait_for)
                pages.append(HtmlPage(url=page.url, html=await page.content()))
            return pages
        finally:
            await page.close()

    async def _open(self, page: Page, url: str, wait_for: str | None) -> None:
        try:
            await self._watched(page.goto(url, wait_until="load" if wait_for else "networkidle"))
        except PlaywrightError as err:
            self._interceptor.raise_fatal()
            raise _fetch_error(url, err) from None
        await self._settle(page, wait_for)

    async def _settle(self, page: Page, wait_for: str | None) -> None:
        """Wait for `wait_for` when given; otherwise until the network goes quiet."""
        try:
            if wait_for:
                await self._watched(page.wait_for_selector(f"css={wait_for}"))
            else:
                await self._watched(page.wait_for_load_state("networkidle"))
        except PlaywrightError as err:
            self._interceptor.raise_fatal()
            raise _fetch_error(page.url, err) from None
        self._interceptor.raise_fatal()

    async def _watched(self, call: Awaitable[Any]) -> None:
        """Await a page call, but stop as soon as a request has failed the run."""
        async with anyio.create_task_group() as group:

            async def stop_on_failure() -> None:
                await self._interceptor.failed.wait()
                group.cancel_scope.cancel()

            group.start_soon(stop_on_failure)
            await call
            group.cancel_scope.cancel()
        self._interceptor.raise_fatal()

    async def _click_next(self, page: Page, selector: str) -> bool:
        button = await page.query_selector(f"css={selector}")
        if button is None or not await button.is_enabled():
            return False
        await button.click()
        return True


def _fetch_error(url: str, err: PlaywrightError) -> FetchError:
    if isinstance(err, PlaywrightTimeout):
        return FetchTimeout(f"headless: {url}: {err.message.splitlines()[0]}")
    return FetchError(f"headless: {url}: {err.message.splitlines()[0]}")


@asynccontextmanager
async def headless_browser(
    session: FetchSession, *, user_agent: str, timeout_s: float
) -> AsyncIterator[HeadlessBrowser]:
    """Launch Chromium for one run, wired to the run's session; it is closed on exit.

    The whole block runs under the run's time limit. Closing the browser is
    shielded from that limit, so a timed-out run still shuts Chromium down.
    """
    interceptor = _Interceptor(session)
    try:
        with anyio.fail_after(timeout_s):
            async with _chromium() as browser:
                context = await _guarded_context(browser, interceptor, user_agent, timeout_s)
                yield HeadlessBrowser(context, interceptor)
    except TimeoutError:
        raise FetchTimeout(f"run exceeded {timeout_s:g}s") from None


@asynccontextmanager
async def _chromium() -> AsyncIterator:
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(proxy={"server": DEAD_PROXY})
        except PlaywrightError as err:
            raise HeadlessUnavailable(f"can't start headless Chromium: {err.message}") from None
        try:
            yield browser
        finally:
            with anyio.CancelScope(shield=True), anyio.move_on_after(_CLOSE_GRACE_S):
                await browser.close()


async def _guarded_context(
    browser, interceptor: _Interceptor, user_agent: str, timeout_s: float
) -> BrowserContext:
    context = await browser.new_context(user_agent=user_agent, service_workers="block")
    context.set_default_timeout(timeout_s * 1000)
    await context.route("**/*", interceptor.handle)
    await context.route_web_socket("**/*", _refuse_socket)
    return context
