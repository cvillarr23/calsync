from dataclasses import dataclass


@dataclass(frozen=True)
class Calendar:
    """A calendar the user can write to, as the source form offers it."""

    id: str
    summary: str
    primary: bool = False
