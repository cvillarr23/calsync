"""HTTP errors in the API's shape: 422 bodies are lists of `{"loc", "msg"}` rows."""

from fastapi import HTTPException, status

UNPROCESSABLE = 422
"""Starlette renamed its 422 constant; the number is stable."""


def unprocessable(problems: list[dict[str, str]]) -> HTTPException:
    return HTTPException(UNPROCESSABLE, problems)


def not_found(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)
