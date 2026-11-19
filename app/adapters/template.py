"""`{{var}}` templates for adapter definitions.

This is deliberately not Jinja: an expression is a variable name, optionally
formatted as a date (`{{date:%Y-%m-%d}}`) or passed through one whitelisted
helper (`{{origin(page_url)}}`). Nothing is evaluated, so a definition can't run code.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlsplit

_TAG = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_EXPR = re.compile(
    rf"""^\s*(?:
        (?P<helper>{_NAME})\(\s*(?P<arg>{_NAME})\s*\)   # origin(page_url)
        | (?P<name>{_NAME})(?::(?P<fmt>[^{{}}]+))?          # date or date:%Y-%m-%d
    )\s*$""",
    re.VERBOSE,
)


class TemplateError(ValueError):
    """A template is malformed, uses something outside the whitelist, or can't be rendered."""


def _origin(value: Any) -> str:
    """`https://host:port` of a URL, so a definition can build sibling API URLs."""
    parts = urlsplit(str(value))
    if not parts.scheme or not parts.netloc:
        raise TemplateError(f"origin() needs an absolute URL, got {value!r}")
    return f"{parts.scheme}://{parts.netloc}"


HELPERS: dict[str, Callable[[Any], Any]] = {"origin": _origin}


@dataclass(frozen=True)
class Expr:
    """One `{{...}}` tag: a variable, plus an optional helper or date format."""

    name: str
    helper: str | None = None
    fmt: str | None = None


Segment = str | Expr


def parse(text: str) -> list[Segment]:
    """Split a template into literal text and expressions, rejecting anything not whitelisted."""
    segments: list[Segment] = []
    pos = 0
    for match in _TAG.finditer(text):
        _append_literal(segments, text[pos : match.start()])
        segments.append(_parse_expr(match.group(1)))
        pos = match.end()
    _append_literal(segments, text[pos:])
    return segments


def names(text: str) -> set[str]:
    """Every variable a template reads."""
    return {seg.name for seg in parse(text) if isinstance(seg, Expr)}


def check(text: str, known: set[str]) -> None:
    """Fail unless the template parses and reads only variables in `known`."""
    unknown = sorted(names(text) - known)
    if unknown:
        raise TemplateError(f"unknown variable(s): {', '.join(unknown)}")


def render(text: str, ctx: Mapping[str, Any]) -> str:
    """Render to a string; objects are embedded as JSON and dates as ISO 8601."""
    return "".join(
        seg if isinstance(seg, str) else _to_text(_evaluate(seg, ctx)) for seg in parse(text)
    )


def render_value(value: Any, ctx: Mapping[str, Any]) -> Any:
    """Render every string inside a JSON-like value.

    A string that is exactly one tag yields the variable's raw value, so
    `data: "{{browse_data}}"` embeds the object itself, not its JSON text.
    """
    if isinstance(value, dict):
        return {key: render_value(item, ctx) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, ctx) for item in value]
    if isinstance(value, str):
        return _render_string_value(value, ctx)
    return value


def strings(value: Any) -> list[str]:
    """Every string inside a JSON-like value, for checking embedded templates."""
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return [value] if isinstance(value, str) else []


def _append_literal(segments: list[Segment], literal: str) -> None:
    if "{{" in literal or "}}" in literal:
        raise TemplateError(f"unbalanced '{{{{' or '}}}}' in {literal!r}")
    if literal:
        segments.append(literal)


def _parse_expr(body: str) -> Expr:
    match = _EXPR.match(body)
    if not match:
        raise TemplateError(f"unsupported expression {{{{{body}}}}}")
    if match["helper"]:
        return _helper_expr(match["helper"], match["arg"])
    return Expr(name=match["name"], fmt=match["fmt"])


def _helper_expr(helper: str, arg: str) -> Expr:
    if helper not in HELPERS:
        allowed = ", ".join(sorted(HELPERS))
        raise TemplateError(f"unknown helper {helper}(); allowed: {allowed}")
    return Expr(name=arg, helper=helper)


def _evaluate(expr: Expr, ctx: Mapping[str, Any]) -> Any:
    if expr.name not in ctx:
        raise TemplateError(f"unknown variable: {expr.name}")
    value = ctx[expr.name]
    if expr.helper:
        return HELPERS[expr.helper](value)
    if expr.fmt:
        return _format_date(expr, value)
    return value


def _format_date(expr: Expr, value: Any) -> str:
    if not isinstance(value, date):
        raise TemplateError(f"{expr.name} is not a date, so it can't take a format")
    return value.strftime(expr.fmt or "")


def _render_string_value(text: str, ctx: Mapping[str, Any]) -> Any:
    segments = parse(text)
    if len(segments) == 1 and isinstance(segments[0], Expr):
        return _evaluate(segments[0], ctx)
    return render(text, ctx)


def _to_text(value: Any) -> str:
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
