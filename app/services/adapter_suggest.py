"""Suggesting an adapter for a pasted calendar URL from each definition's `match_hosts`."""

from collections.abc import Iterable
from urllib.parse import urlsplit

from app.adapters.schema import AdapterDefinition


def suggest_adapters(definitions: Iterable[AdapterDefinition], url: str) -> list[AdapterDefinition]:
    """Definitions whose `match_hosts` names the URL's host or a parent domain of it."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    if not host:
        return []
    return [d for d in definitions if any(_host_matches(host, h) for h in d.match_hosts)]


def _host_matches(host: str, pattern: str) -> bool:
    pattern = pattern.lower().lstrip("*.")
    return host == pattern or host.endswith("." + pattern)
