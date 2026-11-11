"""REST errors: RFC 9457 problem details carrying the stable ``ErrorCode`` (spec 06 C-R4).

One table gives the HTTP status of every code, so a status is decided in one place. The old
service read a class attribute and answered 400 for every ``ApiError`` (``api/main.py:112``).
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import JsonValue
from starlette.exceptions import HTTPException

from app.domain.errors import DomainError, ErrorCode
from app.domain.types import Value
from app.logs import get_logger

log = get_logger("api.problem")

PROBLEM_MEDIA_TYPE = "application/problem+json"

STATUS: dict[ErrorCode, int] = {  # every code has a row: tests/api/test_problems.py checks it
    ErrorCode.Unauthenticated: 401,
    ErrorCode.Forbidden: 403,
    ErrorCode.BadUserInput: 422,
    ErrorCode.NotFound: 404,
    ErrorCode.AssetNotFound: 404,
    ErrorCode.AssetNotReady: 409,
    ErrorCode.AssetTooLarge: 422,
    ErrorCode.AssetUnreadable: 422,
    ErrorCode.ContentEmpty: 404,
    ErrorCode.PlotDataNotFound: 404,
    ErrorCode.ValidationResultNotFound: 404,
    ErrorCode.EntitycoreUnavailable: 503,
    ErrorCode.Internal: 500,
}

# Errors Starlette raises itself (no route, a bearer scheme FastAPI refused, a wrong method).
HTTP_CODES: dict[int, ErrorCode] = {
    401: ErrorCode.Unauthenticated,
    403: ErrorCode.Forbidden,
    404: ErrorCode.NotFound,
}


class Problem(Value):
    """An RFC 9457 problem; ``code`` is the stable ``ErrorCode``, ``errors`` the input details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: ErrorCode
    errors: list[JsonValue] | None = None


def title_of(code: ErrorCode) -> str:
    """A short title from the code.

    Examples:
        >>> title_of(ErrorCode.AssetNotFound)
        'Asset not found'
    """
    return code.value.capitalize().replace("_", " ")


def problem(
    code: ErrorCode,
    detail: str,
    *,
    status: int | None = None,
    errors: list[JsonValue] | None = None,
) -> JSONResponse:
    """The HTTP answer of an error code (status from :data:`STATUS` unless given)."""
    status = status or STATUS[code]
    body = Problem(title=title_of(code), status=status, detail=detail, code=code, errors=errors)
    headers = (
        {"WWW-Authenticate": "Bearer"} if status == HTTPStatus.UNAUTHORIZED else None
    )  # RFC 6750 §3
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def _domain(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, DomainError)  # noqa: S101 - registered for DomainError only
    emit = log.error if STATUS[error.code] >= HTTPStatus.INTERNAL_SERVER_ERROR else log.info
    emit("request refused", code=error.code.value, **error.details)
    return problem(error.code, error.message)


async def _invalid(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)  # noqa: S101 - registered for it only
    errors: list[JsonValue] = [
        {"loc": [str(part) for part in e["loc"]], "msg": e["msg"], "type": e["type"]}
        for e in error.errors()
    ]
    return problem(ErrorCode.BadUserInput, "The request is not valid", errors=errors)


async def _http(_: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, HTTPException)  # noqa: S101 - registered for it only
    code = HTTP_CODES.get(error.status_code, ErrorCode.BadUserInput)
    return problem(code, str(error.detail), status=error.status_code)


async def _crash(_: Request, error: Exception) -> JSONResponse:
    log.error("request failed", exc_info=error)
    return problem(ErrorCode.Internal, "Internal error")  # raw exception text never leaves


def install(app: FastAPI) -> None:
    """Answer every error of ``app`` as a problem (one edge, spec 06 C-E5)."""
    app.add_exception_handler(DomainError, _domain)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(Exception, _crash)
