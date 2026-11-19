"""Reading the document a step works on: JSON decoding and JSONPath lookups."""

import json
from functools import lru_cache
from typing import Any

from jsonpath_ng import JSONPath
from jsonpath_ng.ext import parse as parse_jsonpath


class DocumentError(ValueError):
    """The document isn't what the step expected; the caller names the step."""


@lru_cache(maxsize=256)
def compiled(path: str) -> JSONPath:
    """Paths are validated when a definition is saved, so this only parses known-good ones."""
    return parse_jsonpath(path)


def first_match(path: str, document: Any) -> Any:
    matches = compiled(path).find(document)
    if not matches:
        raise DocumentError(f"JSONPath {path} matched nothing")
    return matches[0].value


def all_matches(path: str, document: Any) -> list[Any]:
    return [match.value for match in compiled(path).find(document)]


def as_json(document: Any) -> Any:
    """A text document is decoded first, so JSONPath can read a JSON response body."""
    return parsed_json(document) if isinstance(document, str) else document


def parsed_json(value: Any) -> Any:
    if not isinstance(value, str):
        raise DocumentError(f"parse: json needs a string, got {type(value).__name__}")
    try:
        return json.loads(value)
    except json.JSONDecodeError as err:
        raise DocumentError(f"not valid JSON: {err}") from None


def as_text(document: Any) -> str:
    return document if isinstance(document, str) else json.dumps(document)
