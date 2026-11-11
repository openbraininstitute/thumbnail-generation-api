"""The one error vocabulary of the service: REST problem ``code`` and logs (spec 06 C-E1).

One flat ``StrEnum``: the service has one area, so the grouping workspace-manager needs is not
needed here. A code is never reused for another meaning. Codes kept from the old service keep
their value (``ASSET_NOT_FOUND``, ``CONTENT_EMPTY``, ``VALIDATION_RESULT_NOT_FOUND``) so a
client that matched them still does. The HTTP status of each code is in ``api/problems.py``.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes."""

    Unauthenticated = "UNAUTHENTICATED"  # no bearer token, or entitycore refused it
    Forbidden = "FORBIDDEN"  # entitycore said 403
    BadUserInput = "BAD_USER_INPUT"  # a query, path or header value was refused
    NotFound = "NOT_FOUND"  # no such route
    AssetNotFound = "ASSET_NOT_FOUND"  # kept: entity or asset missing, or not readable by caller
    AssetNotReady = "ASSET_NOT_READY"  # new: entitycore 409, the asset is still uploading
    AssetTooLarge = "ASSET_TOO_LARGE"  # new: over ENTITY_CORE_MAX_ASSET_BYTES
    AssetUnreadable = "ASSET_UNREADABLE"  # new: the file is not the SWC/NWB/JSON a renderer reads
    ContentEmpty = "CONTENT_EMPTY"  # kept: the asset has no bytes
    PlotDataNotFound = "PLOT_DATA_NOT_FOUND"  # new: a simulation file without the asked target
    ValidationResultNotFound = "VALIDATION_RESULT_NOT_FOUND"  # kept: no model-trace thumbnail
    EntitycoreUnavailable = "ENTITYCORE_UNAVAILABLE"  # new: timeout, network, 5xx or 429
    Internal = "INTERNAL"  # a crash, masked: raw exception text never reaches a client


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
