"""HTTP errors in the API's shape: 422 bodies are lists of `{"loc", "msg"}` rows."""

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from app.services.errors import Conflict, Invalid, NotFound, ServiceError

UNPROCESSABLE = 422
"""Starlette renamed its 422 constant; the number is stable."""

_STATUS = {NotFound: 404, Conflict: 409, Invalid: UNPROCESSABLE}


def status_for(err: ServiceError) -> int:
    return _STATUS.get(type(err), status.HTTP_400_BAD_REQUEST)


def service_error_response(err: ServiceError) -> JSONResponse:
    """`{"detail": ...}`, the same body FastAPI gives an `HTTPException`."""
    detail = err.problems if isinstance(err, Invalid) else str(err)
    return JSONResponse({"detail": detail}, status_code=status_for(err))


def not_found(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, msg)
