import dataclasses
from enum import auto
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel

from api.core.enum import UpperStrEnum


class ApiErrorCode(UpperStrEnum):
    """API Error codes."""

    GENERIC_ERROR = auto()
    ASSET_NOT_FOUND = auto()
    CONTENT_EMPTY = auto()
    REMOTE_ASSET_NOT_FOUND = auto()
    BUFFERING_ERROR = auto()
    INTERNAL_ERROR = auto()
    VALIDATION_RESULT_NOT_FOUND = auto()


@dataclasses.dataclass(kw_only=True)
class ApiError(Exception):
    """API Error."""

    message: str
    error_code: ApiErrorCode
    http_status_code: HTTPStatus | int = HTTPStatus.BAD_REQUEST
    details: Any = None

    def __repr__(self) -> str:
        """Return the repr of the error."""
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code}, "
            f"http_status_code={self.http_status_code}, "
            f"details={self.details!r})"
        )

    def __str__(self) -> str:
        """Return the str representation."""
        return (
            f"message={self.message!r} "
            f"error_code={self.error_code} "
            f"http_status_code={self.http_status_code} "
            f"details={self.details!r}"
        )


class ErrorResponse(BaseModel, use_enum_values=True):
    """ErrorResponse."""

    error_code: ApiErrorCode
    message: str
    details: Any = None
