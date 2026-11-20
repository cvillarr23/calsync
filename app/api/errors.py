"""HTTP errors in the API's shape: 422 bodies are lists of `{"loc", "msg"}` rows."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.services.errors import Conflict, Invalid, NotFound, ServiceError

UNPROCESSABLE = 422
"""Starlette renamed its 422 constant; the number is stable."""

_STATUS = {NotFound: 404, Conflict: 409, Invalid: UNPROCESSABLE}


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service_error)


async def _service_error(request: Request, err: Exception) -> JSONResponse:
    """`{"detail": ...}`, the same body FastAPI gives an `HTTPException`."""
    detail = err.problems if isinstance(err, Invalid) else str(err)
    return JSONResponse({"detail": detail}, status_code=_STATUS.get(type(err), 400))


def not_found(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)
