"""Error codes of the service: the ``code`` of every problem and log line.

A code never changes meaning. HTTP status per code: ``api/problems.py``.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes."""

    Unauthenticated = "UNAUTHENTICATED"  # no bearer token, or entitycore refused it
    Forbidden = "FORBIDDEN"  # entitycore said 403
    BadUserInput = "BAD_USER_INPUT"  # a query, path or header value was refused
    NotFound = "NOT_FOUND"  # no such route
    AssetNotFound = "ASSET_NOT_FOUND"  # missing, or not readable by the caller
    AssetNotReady = "ASSET_NOT_READY"  # entitycore 409: still uploading
    AssetTooLarge = "ASSET_TOO_LARGE"  # over ENTITY_CORE_MAX_ASSET_BYTES
    AssetUnreadable = "ASSET_UNREADABLE"  # not the SWC/NWB/JSON the renderer reads
    ContentEmpty = "CONTENT_EMPTY"  # the asset has no bytes
    PlotDataNotFound = "PLOT_DATA_NOT_FOUND"  # no data for the asked target
    ValidationResultNotFound = "VALIDATION_RESULT_NOT_FOUND"  # no model-trace thumbnail
    EntitycoreUnavailable = "ENTITYCORE_UNAVAILABLE"  # timeout, network, 5xx or 429
    Internal = "INTERNAL"  # a crash; its text never reaches a client


class DomainError(Exception):
    """An expected failure, shown to clients as a problem with a stable code.

    Args:
        code: The stable error code.
        message: A safe, human-readable message (never raw exception text).
        details: Structured, safe context for clients (for example a limit).

    Examples:
        >>> error = DomainError(ErrorCode.AssetTooLarge, "Asset too large", limit=10)
        >>> (error.code, error.details)
        (<ErrorCode.AssetTooLarge: 'ASSET_TOO_LARGE'>, {'limit': 10})
    """

    def __init__(self, code: ErrorCode, message: str, **details: object) -> None:
        """Store the code, message and details."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = details
