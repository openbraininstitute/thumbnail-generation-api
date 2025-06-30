"""
Module: exceptions.py

This module defines a custom exception classes
"""

from typing import TypedDict

from fastapi import HTTPException
from sentry_sdk import capture_exception


class ErrorDetail(TypedDict):
    """Error detail dictionary"""

    message: str | None
    code: str


class SentryReportedException(HTTPException):
    """Base class for exceptions that should be reported to Sentry."""

    detail: ErrorDetail

    def __init__(
        self,
        status_code: int,
        detail: ErrorDetail,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Sentry Reported Exception.

        Args:
            status_code: http status code
            detail: detail of the exception
            headers: optional headers
        """
        super().__init__(status_code, detail, headers)
        capture_exception(self)


# Authentication


class InvalidAccessToken(HTTPException):
    """Exception raised when the provided access token is invalid."""

    def __init__(self):
        super().__init__(
            status_code=401,
            detail={
                "message": "Access token invalid",
                "code": self.__class__.__name__,
            },
        )


class ExpiredAccessToken(HTTPException):
    """Exception raised when the provided access token has expired"""

    def __init__(self):
        super().__init__(
            status_code=401,
            detail={
                "message": "Access token expired",
                "code": self.__class__.__name__,
            },
        )


class AuthenticationIssueException(HTTPException):
    """Exception raised when Nexus throws authorization error"""

    def __init__(self):
        super().__init__(
            status_code=401,
            detail={
                "message": "User not authenticated",
                "code": self.__class__.__name__,
            },
        )


class AuthorizationIssueException(HTTPException):
    """Exception raised when Nexus throws authorization error"""

    def __init__(self):
        super().__init__(
            status_code=403,
            detail={
                "message": "User not authorized",
                "code": self.__class__.__name__,
            },
        )


# Nexus


class EntityNotFoundException(HTTPException):
    """Exception raised when a requested resource is not found.

    This exception is typically used to indicate that a resource, such as a file, database record,
    or network endpoint, is expected to exist but cannot be located.
    """

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "Entity not found",
                "code": self.__class__.__name__,
            },
        )


class InvalidUrlParameterException(HTTPException):
    """Exception raised when a URL parameter is empty or invalid.

    This exception is typically used to indicate that a parameter, such as a content_url, is expected to exist,
    and be valid, but instead is either an empty string or simply not a valid URL.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=422,
            detail={
                "message": "Invalid content_url parameter in request",
                "code": self.__class__.__name__,
            },
        )


# Electrophysiology


class NoCellFound(SentryReportedException):
    "Thrown when no cell is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'cell'.",
                "code": self.__class__.__name__,
            },
        )


class NoRepetitionFound(SentryReportedException):
    "Thrown when no repetition is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'repetition'.",
                "code": self.__class__.__name__,
            },
        )


class NoSweepFound(SentryReportedException):
    "Thrown when no sweep is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'sweep'.",
                "code": self.__class__.__name__,
            },
        )


class NoProtocolFound(SentryReportedException):
    "Thrown when no protocol is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'protocol'.",
                "code": self.__class__.__name__,
            },
        )


class NoResponseFound(SentryReportedException):
    "Thrown when no Response data is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain any Response data.",
                "code": self.__class__.__name__,
            },
        )


class NoUnitFound(SentryReportedException):
    "Thrown when no unit is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'unit'.",
                "code": self.__class__.__name__,
            },
        )


class NoRateFound(SentryReportedException):
    "Thrown when no rate is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'rate'.",
                "code": self.__class__.__name__,
            },
        )


class NoConversionFound(SentryReportedException):
    "Thrown when no conversion is found."

    def __init__(self):
        super().__init__(
            status_code=404,
            detail={
                "message": "NWB file didn't contain a 'conversion'.",
                "code": self.__class__.__name__,
            },
        )


class ContentEmpty(SentryReportedException):
    "Thrown when asset content is empty."

    def __init__(self, msg: str | None = "Content is not available"):
        super().__init__(
            status_code=404,
            detail=ErrorDetail(message=msg, code=self.__class__.__name__),
        )


class AssetNotFound(SentryReportedException):
    "Thrown when asset is not found."

    def __init__(self, msg: str | None = "Asset not found"):
        super().__init__(
            status_code=404,
            detail=ErrorDetail(message=msg, code=self.__class__.__name__),
        )


class ValidationResultNotFound(SentryReportedException):
    "Thrown when validation result is not found."

    def __init__(self, msg: str | None = "Validation result not found"):
        super().__init__(
            status_code=404,
            detail=ErrorDetail(message=msg, code=self.__class__.__name__),
        )
