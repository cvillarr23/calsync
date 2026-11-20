"""How service errors and missing sign-in reach the user: JSON under `/api`, pages elsewhere."""

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import NotSignedIn
from app.api.errors import service_error_response, status_for
from app.services.errors import ServiceError
from app.web.rendering import render

LOGIN_PATH = "/auth/login"


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(NotSignedIn, _not_signed_in)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/") or request.url.path == "/api"


async def _service_error(request: Request, err: Exception) -> Response:
    assert isinstance(err, ServiceError)
    if _is_api(request):
        return service_error_response(err)
    return render(request, "error.html", {"message": str(err)}, status_code=status_for(err))


async def _not_signed_in(request: Request, err: Exception) -> Response:
    """htmx swaps fragments, so it gets `HX-Redirect` to load the sign-in page whole."""
    if _is_api(request):
        return JSONResponse({"detail": "sign in first"}, status.HTTP_401_UNAUTHORIZED)
    if request.headers.get("HX-Request"):
        return Response(
            status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": LOGIN_PATH}
        )
    return RedirectResponse(LOGIN_PATH, status.HTTP_303_SEE_OTHER)
