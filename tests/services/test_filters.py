from dataclasses import dataclass

import pytest

from app.services import filters


@dataclass
class Item:
    title: str


def test_public_skate_kept_and_theme_night_dropped():
    events = [Item("Public Skate"), Item("Public Skate Theme Night: EDM/House")]
    kept = filters.apply(events, include=["public skate"], exclude=["theme night"])
    assert [e.title for e in kept] == ["Public Skate"]


def test_normalize_lowercases_and_collapses_whitespace():
    assert filters.normalize("  Public\t Skate \n Night ") == "public skate night"


@pytest.mark.parametrize(
    ("title", "include", "exclude", "expected"),
    [
        ("Anything", [], [], True),
        ("Anything", [""], ["  "], True),
        ("Public   SKATE", ["public skate"], [], True),
        ("Hockey", ["public skate"], [], False),
        ("Hockey", ["public skate", "hockey"], [], True),
        ("Public Skate", ["public skate"], ["PUBLIC"], False),
        ("Public Skate", [], ["theme   night"], True),
        ("Theme\nNight", [], ["theme night"], False),
    ],
)
def test_matches(title, include, exclude, expected):
    assert filters.matches(title, include, exclude) is expected
