"""Running a pipeline's steps: http, extract, paginate and items.

Steps share variables (the params plus anything saved with `as`) and a current
*document*: the last response body, or the last value extracted without `as`.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.adapters import template
from app.adapters.fetch import FetchError, FetchSession
from app.adapters.mappers import Window
from app.adapters.pipeline.documents import (
    DocumentError,
    all_matches,
    as_json,
    as_text,
    first_match,
    parsed_json,
)
from app.adapters.pipeline.errors import CSS_UNSUPPORTED, StepError
from app.adapters.schema import ExtractSpec, HttpSpec, ItemsSpec, Step


class _Failure(Exception):
    """Raised inside a step; `_step_errors` adds which step it was."""


@dataclass
class _State:
    variables: dict[str, Any]
    document: Any = None

    def save(self, name: str | None, value: Any) -> None:
        """Into the named variable, or over the document when there's no name."""
        if name:
            self.variables[name] = value
        else:
            self.document = value

    def fork(self, name: str, value: Any) -> "_State":
        return _State({**self.variables, name: value}, self.document)


@dataclass(frozen=True)
class _Run:
    steps: Sequence[Step]
    session: FetchSession
    window: Window


async def collect_items(
    steps: Sequence[Step],
    params: Mapping[str, Any],
    *,
    session: FetchSession,
    window: Window,
) -> list[Any]:
    """Run the steps and return the records from every page's `items` step."""
    return await _run_steps(_Run(steps, session, window), 0, _State(dict(params)))


async def _run_steps(run: _Run, first: int, state: _State) -> list[Any]:
    """Run steps from `first` on; validation guarantees the last one is `items`."""
    for index in range(first, len(run.steps)):
        step = run.steps[index]
        if step.paginate is not None:
            return await _paginate(run, index, state)
        with _step_errors(index, step.kind):
            if step.items is not None:
                return _items(step.items, state)
            await _apply(run.session, step, state)
    return []


async def _apply(session: FetchSession, step: Step, state: _State) -> None:
    if step.http is not None:
        await _http(session, step.http, state)
    elif step.extract is not None:
        _extract(step.extract, state)


@contextmanager
def _step_errors(index: int, kind: str) -> Iterator[None]:
    """Name the failing step, so the editor can point at it."""
    try:
        yield
    except (_Failure, DocumentError, FetchError, template.TemplateError) as err:
        raise StepError(index, kind, str(err)) from None


async def _paginate(run: _Run, index: int, state: _State) -> list[Any]:
    """Run the remaining steps once per page date, concatenating their items.

    The variable holds a `datetime`, not a string, so templates can format it
    with `{{date:%Y-%m-%d}}`.
    """
    spec = run.steps[index].paginate
    assert spec is not None
    items: list[Any] = []
    for day in _page_dates(run.window, spec.step_days):
        items += await _run_steps(run, index + 1, state.fork(spec.as_, day))
    return items


def _page_dates(window: Window, step_days: int) -> Iterator[datetime]:
    """Midnight on every `step_days`-th date from the window's first date through its last."""
    days = (window.end - window.start).days + 1
    for offset in range(0, max(days, 1), step_days):
        yield window.base + timedelta(days=offset)


async def _http(session: FetchSession, spec: HttpSpec, state: _State) -> None:
    url = template.render(spec.url, state.variables)
    page = await session.fetch(
        url,
        method=spec.method,
        headers=_render_all(spec.headers, state.variables),
        json=_json_body(spec, state.variables),
        data=_render_all(spec.form, state.variables) if spec.form is not None else None,
        follow_redirects=spec.follow_redirects,
    )
    if page.status_code >= 400:
        raise _Failure(f"{spec.method} {url} returned HTTP {page.status_code}")
    state.document = page.text


def _render_all(values: Mapping[str, str], variables: Mapping[str, Any]) -> dict[str, str]:
    return {key: template.render(value, variables) for key, value in values.items()}


def _json_body(spec: HttpSpec, variables: Mapping[str, Any]) -> Any:
    return None if spec.json_ is None else template.render_value(spec.json_, variables)


def _extract(spec: ExtractSpec, state: _State) -> None:
    value = _extracted(spec, state.document)
    if spec.parse == "json":
        value = parsed_json(value)
    state.save(spec.as_, value)


def _extracted(spec: ExtractSpec, document: Any) -> Any:
    if spec.regex is not None:
        return _first_group(spec.regex, as_text(document))
    if spec.jsonpath is not None:
        return first_match(spec.jsonpath, as_json(document))
    raise _Failure(CSS_UNSUPPORTED)


def _first_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise _Failure(f"regex {pattern!r} matched nothing")
    return match.group(1)


def _items(spec: ItemsSpec, state: _State) -> list[Any]:
    if spec.jsonpath is None:
        raise _Failure(CSS_UNSUPPORTED)
    return all_matches(spec.jsonpath, as_json(state.document))
