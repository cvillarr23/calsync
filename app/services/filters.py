"""Include/exclude keyword filters for a source's events.

Titles and keywords are compared after normalising both: lowercase, with runs
of whitespace collapsed to one space. A keyword matches when it appears
anywhere in the title. An exclude match always wins, and an empty include list
matches everything.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Protocol

_WHITESPACE = re.compile(r"\s+")


class Titled(Protocol):
    @property
    def title(self) -> str: ...


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().lower()


def matches(title: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    text = normalize(title)
    if _any_in(text, exclude):
        return False
    return not _keywords(include) or _any_in(text, include)


def apply[T: Titled](
    events: Iterable[T], include: Sequence[str], exclude: Sequence[str]
) -> list[T]:
    """The events whose titles pass the filter, in their original order."""
    return [event for event in events if matches(event.title, include, exclude)]


def _keywords(words: Sequence[str]) -> list[str]:
    """Normalised keywords; blank entries are dropped so `[""]` means no keywords."""
    return [word for word in map(normalize, words) if word]


def _any_in(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in _keywords(words))
