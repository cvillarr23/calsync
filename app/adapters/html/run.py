"""Running an html definition, directly or as the sync core's engine for the html kind."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.adapters.events import AdapterRunError, ScrapedEvent
from app.adapters.fetch import (
    AddressGuard,
    FetchError,
    FetchLimits,
    FetchSession,
    PageCache,
    Resolver,
    resolve,
)
from app.adapters.html.extract import extract
from app.adapters.html.pages import fetch_pages
from app.adapters.html.result import RunResult
from app.adapters.mappers import Window
from app.adapters.schema import AdapterDefinition, HtmlDefinition


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

    `params` are the source's values with defaults already applied. Fetch
    failures and broken limits raise `FetchError`. A field that can't be read is
    reported in `problems` and only drops its own item.
    """
    session = FetchSession(
        limits,
        guard=guard,
        cache=cache,
        user_agent=definition.fetch.user_agent,
        resolver=resolver,
    )
    async with session:
        pages = await fetch_pages(definition, params, window, session, limits)
    return extract(definition, pages, window)


class HtmlEngine:
    """The `AdapterRunner` engine for the html kind, bound to the instance's fetch limits."""

    def __init__(self, limits: FetchLimits, **run_options: Any) -> None:
        self._limits = limits
        self._run_options = run_options

    async def __call__(
        self,
        definition: AdapterDefinition,
        params: Mapping[str, Any],
        window_start: datetime,
        window_end: datetime,
    ) -> list[ScrapedEvent]:
        if not isinstance(definition, HtmlDefinition):
            raise AdapterRunError(f"the html engine can't run a {definition.kind} definition")
        window = Window.between(window_start, window_end)
        try:
            result = await run_html(
                definition, params, window, limits=self._limits, **self._run_options
            )
        except FetchError as err:
            raise AdapterRunError(str(err)) from err
        _fail_if_nothing_read(result)
        return [e for e in result.events if _in_window(e, window_start, window_end)]


def _fail_if_nothing_read(result: RunResult) -> None:
    """Every item failed: report the first reason instead of syncing an empty calendar."""
    if result.problems and not result.events:
        more = len(result.problems) - 1
        suffix = f" (and {more} more)" if more else ""
        raise AdapterRunError(f"no event could be read: {result.problems[0]}{suffix}")


def _in_window(event: ScrapedEvent, window_start: datetime, window_end: datetime) -> bool:
    return (event.end_utc or event.start_utc) >= window_start and event.start_utc <= window_end
