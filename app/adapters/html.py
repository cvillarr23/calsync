"""Run `kind: html` definitions: fetch pages, select items with CSS, map them to events.

Both fetch modes end in the same place: selectolax parses the HTML, whether it was
served directly (static) or rendered by headless Chromium. Headless mode only
supplies the HTML.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.adapters import template
from app.adapters.fetch import (
    DEFAULT_USER_AGENT,
    AddressGuard,
    FetchError,
    FetchLimits,
    FetchSession,
    PageCache,
    Resolver,
    resolve,
)
from app.adapters.headless import HtmlPage, headless_browser
from app.adapters.mapping import Event, FieldFailure, Reader, Window, map_item
from app.adapters.schema import FieldSpec, HtmlDefinition


@dataclass(frozen=True)
class FieldProblem:
    """A field that couldn't be read from one item; that item was left out."""

    page: str
    item: int
    field: str
    msg: str


@dataclass
class RunResult:
    events: list[Event] = field(default_factory=list)
    problems: list[FieldProblem] = field(default_factory=list)


async def run_html(
    definition: HtmlDefinition,
    params: Mapping[str, Any],
    window: Window,
    *,
    limits: FetchLimits,
    cache: PageCache | None = None,
    guard: AddressGuard | None = None,
    resolver: Resolver = resolve,
) -> RunResult:
    """Fetch every page the definition asks for and map its items to events.

    Fetch failures and broken limits raise `FetchError`. A field that can't be
    read is reported in `problems` and only drops its own item.
    """
    session = FetchSession(
        limits,
        guard=guard,
        cache=cache,
        user_agent=definition.fetch.user_agent,
        resolver=resolver,
    )
    async with session:
        pages = await _fetch_pages(definition, params, window, session, limits)
    return _extract(definition, pages, window)


def _page_urls(definition: HtmlDefinition, params: Mapping[str, Any], window: Window) -> list[str]:
    """`fetch.url`, or `pagination.url_template` once per `step_days` across the window."""
    variables = _with_defaults(definition, params)
    pagination = definition.pagination
    if pagination.mode != "url_template":
        return [template.render(definition.fetch.url or "", variables)]
    step = timedelta(days=pagination.step_days or 1)
    urls, day = [], window.start
    while day <= window.end:
        urls.append(template.render(pagination.url_template or "", {**variables, "date": day}))
        day += step
    return urls


def _with_defaults(definition: HtmlDefinition, params: Mapping[str, Any]) -> dict[str, Any]:
    defaults = {name: p.default for name, p in definition.params.items() if p.default is not None}
    return {**defaults, **params}


async def _fetch_pages(
    definition: HtmlDefinition,
    params: Mapping[str, Any],
    window: Window,
    session: FetchSession,
    limits: FetchLimits,
) -> list[HtmlPage]:
    urls = _page_urls(definition, params, window)
    if definition.fetch.mode == "headless":
        return await _headless_pages(definition, urls, session, limits)
    return [await _static_page(session, url) for url in urls]


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


def _extract(definition: HtmlDefinition, pages: list[HtmlPage], window: Window) -> RunResult:
    """Map every item on every page, keeping the first event for each uid."""
    result, seen = RunResult(), set()
    for page in pages:
        tree = LexborHTMLParser(page.html)
        contexts = _ContextIndex(tree)
        for index, node in enumerate(tree.css(definition.item)):
            read = _reader(node, page.url, contexts)
            try:
                event = map_item(definition.map, read, window, definition.uid)
            except FieldFailure as failure:
                result.problems.append(FieldProblem(page.url, index, failure.field, failure.msg))
                continue
            if event is not None and event.uid not in seen:
                seen.add(event.uid)
                result.events.append(event)
    return result


class _ContextIndex:
    """Finds `from_context` matches: the last match that starts before the item.

    In document order, an element's ancestors and everything before it come
    first, so this is the nearest ancestor or preceding element, such as the date
    header above a cell in a week grid.
    """

    def __init__(self, tree: LexborHTMLParser) -> None:
        self._tree = tree
        self._order = {node.mem_id: n for n, node in enumerate(_all_elements(tree))}
        self._matches: dict[str, list[tuple[int, LexborNode]]] = {}

    def before(self, node: LexborNode, selector: str) -> LexborNode | None:
        position = self._order[node.mem_id]
        found = None
        for order, match in self._ordered_matches(selector):
            if order >= position:
                break
            found = match
        return found

    def _ordered_matches(self, selector: str) -> list[tuple[int, LexborNode]]:
        if selector not in self._matches:
            matches = [(self._order[m.mem_id], m) for m in self._tree.css(selector)]
            self._matches[selector] = sorted(matches, key=lambda pair: pair[0])
        return self._matches[selector]


def _all_elements(tree: LexborHTMLParser) -> list[LexborNode]:
    root = tree.root
    return [] if root is None else list(root.traverse(include_text=False))


def _reader(node: LexborNode, page_url: str, contexts: _ContextIndex) -> Reader:
    """Reads fields from one item node: `selector` inside it, or `from_context` before it."""

    def read(spec: FieldSpec, name: str) -> str | None:
        found = _field_node(node, spec, contexts)
        if found is None:
            return None
        value = found.attributes.get(spec.attr) if spec.attr else _text(found)
        return urljoin(page_url, value) if name == "url" and value else value

    return read


def _field_node(node: LexborNode, spec: FieldSpec, contexts: _ContextIndex) -> LexborNode | None:
    if spec.from_context is not None:
        return contexts.before(node, spec.from_context)
    return node.css_first(spec.selector or "")


def _text(node: LexborNode) -> str:
    """The node's text with runs of whitespace collapsed to single spaces."""
    return " ".join(node.text(deep=True, separator=" ").split())
