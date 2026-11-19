"""Getting each page's HTML: which URLs to read, and reading them statically or headless."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from app.adapters import template
from app.adapters.fetch import DEFAULT_USER_AGENT, FetchError, FetchLimits, FetchSession
from app.adapters.html.headless import headless_browser
from app.adapters.html.page import HtmlPage
from app.adapters.mappers import Window
from app.adapters.schema import HtmlDefinition


async def fetch_pages(
    definition: HtmlDefinition,
    params: Mapping[str, Any],
    window: Window,
    session: FetchSession,
    limits: FetchLimits,
) -> list[HtmlPage]:
    urls = page_urls(definition, params, window)
    if definition.fetch.mode == "headless":
        return await _headless_pages(definition, urls, session, limits)
    return [await _static_page(session, url) for url in urls]


def page_urls(definition: HtmlDefinition, params: Mapping[str, Any], window: Window) -> list[str]:
    """`fetch.url`, or `pagination.url_template` once per `step_days` across the window."""
    pagination = definition.pagination
    if pagination.mode != "url_template":
        return [template.render(definition.fetch.url or "", params)]
    step = timedelta(days=pagination.step_days or 1)
    urls, day = [], window.start
    while day <= window.end:
        urls.append(template.render(pagination.url_template or "", {**params, "date": day}))
        day += step
    return urls


async def _static_page(session: FetchSession, url: str) -> HtmlPage:
    page = await session.fetch(url)
    if page.status_code >= 400:
        raise FetchError(f"GET {url}: HTTP {page.status_code}")
    return HtmlPage(url=page.url, html=page.text)


async def _headless_pages(
    definition: HtmlDefinition, urls: list[str], session: FetchSession, limits: FetchLimits
) -> list[HtmlPage]:
    fetch, pagination = definition.fetch, definition.pagination
    user_agent = fetch.user_agent or DEFAULT_USER_AGENT
    async with headless_browser(
        session, user_agent=user_agent, timeout_s=limits.timeout_s
    ) as browser:
        if pagination.mode == "click_next":
            selector, max_pages = pagination.selector or "", pagination.max_pages or 1
            return await browser.click_through(urls[0], fetch.wait_for, selector, max_pages)
        return [await browser.render(url, fetch.wait_for) for url in urls]
