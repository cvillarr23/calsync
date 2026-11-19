from dataclasses import dataclass


@dataclass(frozen=True)
class HtmlPage:
    """One page's HTML, as served (static) or as rendered (headless)."""

    url: str
    html: str
