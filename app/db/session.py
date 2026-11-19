"""The per-request database session dependency."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    """One session per request, committed when the handler succeeds."""
    with request.app.state.sessions.begin() as session:
        yield session


Db = Annotated[Session, Depends(get_db, scope="function")]
"""A request's session. Function scope commits before the response is sent, so a
client that gets a 201 can read its write back on the next request."""
