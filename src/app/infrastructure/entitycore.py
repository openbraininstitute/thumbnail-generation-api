"""The entitycore adapter over HTTP (implements ``application.ports.EntityCore``).

One ``httpx2.AsyncClient`` per process, made in the app lifespan: connections to entitycore and
to the storage are kept alive and reused (the old service opened a new client, so a new TCP and
TLS handshake, on every request).

Every entitycore call carries the caller's token and project headers: entitycore applies its
own rule (public, or in one of the caller's projects). This adapter never decides access.

Errors are translated once, here, with one table (spec 06 C-E5): a 401, 403, 404, 409 or 4xx
from entitycore keeps its meaning; a timeout, a network failure, a 429 or a 5xx is
``ENTITYCORE_UNAVAILABLE`` (503, the caller may retry).
"""

import time
from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Any
from uuid import UUID

import httpx2

from app.domain.errors import DomainError, ErrorCode
from app.domain.guards import ensure, match_error, require
from app.domain.preview import Asset, Caller, EntityRoute
from app.logs import get_logger

log = get_logger("http.entitycore")

THUMBNAIL_VALIDATION = "thumbnail"  # the validation result that holds a model's trace image
MODEL_TRACE_MEDIA_TYPE = "image/png"
REDIRECTS = frozenset({301, 302, 303, 307, 308})


def refused(status: int, not_found: ErrorCode, what: str) -> DomainError:
    """The error of a non-2xx entitycore answer.

    Examples:
        >>> refused(404, ErrorCode.AssetNotFound, "Asset").code.value
        'ASSET_NOT_FOUND'
        >>> refused(503, ErrorCode.AssetNotFound, "Asset").code.value
        'ENTITYCORE_UNAVAILABLE'
    """
    table: dict[int, tuple[ErrorCode, str]] = {
        HTTPStatus.UNAUTHORIZED: (ErrorCode.Unauthenticated, "The token was refused"),
        HTTPStatus.FORBIDDEN: (ErrorCode.Forbidden, f"{what} may not be read"),
        HTTPStatus.NOT_FOUND: (not_found, f"{what} not found or not readable"),
        HTTPStatus.CONFLICT: (ErrorCode.AssetNotReady, f"{what} is still being uploaded"),
        HTTPStatus.BAD_REQUEST: (ErrorCode.BadUserInput, "entitycore refused the request"),
        HTTPStatus.UNPROCESSABLE_ENTITY: (ErrorCode.BadUserInput, "entitycore refused the request"),
    }
    code, message = table.get(
        status, (ErrorCode.EntitycoreUnavailable, "entitycore is not available")
    )
    return DomainError(code, message, upstream_status=status)


def unavailable(_: Exception) -> DomainError:
    """A network failure or an answer this adapter cannot read."""
    return DomainError(ErrorCode.EntitycoreUnavailable, "entitycore is not available")


def asset_of(row: Mapping[str, Any]) -> Asset:
    """The fields of an entitycore ``AssetRead`` this service uses.

    Examples:
        >>> asset_of({"id": str(UUID(int=1)), "content_type": "a/b", "size": 3, "x": 1}).size
        3
    """
    return Asset(
        id=row["id"],
        content_type=row["content_type"],
        size=row["size"],
        sha256_digest=row.get("sha256_digest"),
    )


class HttpEntityCore:
    """entitycore over HTTP.

    Args:
        client: The process's HTTP client (the caller owns and closes it).
        base_url: Root of the entitycore API.
        max_asset_bytes: Largest asset downloaded.
    """

    def __init__(self, client: httpx2.AsyncClient, *, base_url: str, max_asset_bytes: int) -> None:
        """Store the configuration."""
        self._client = client
        self._base = base_url.rstrip("/")
        self._max = max_asset_bytes

    async def asset(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset_id: UUID
    ) -> Asset:
        """The asset's metadata (size, sha256), read with the caller's token."""
        row = await self._json(caller, f"/{route}/{entity_id}/assets/{asset_id}", what="Asset")
        return self._parsed(lambda: asset_of(row))

    async def content(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset: Asset
    ) -> bytes:
        """The asset's bytes: entitycore redirects to a presigned storage URL, read in a stream.

        Raises:
            DomainError: ``ASSET_TOO_LARGE`` over the limit (checked from the metadata, then
                while reading); ``CONTENT_EMPTY`` for no bytes.
        """
        self._within_limit(asset.size)
        path = f"/{route}/{entity_id}/assets/{asset.id}/download"
        response = await self._send(caller, path)
        if response.status_code not in REDIRECTS:
            raise refused(response.status_code, ErrorCode.AssetNotFound, "Asset")
        location = require(
            response.headers.get("location"), ErrorCode.ContentEmpty, "No download location"
        )
        # Only a web URL is followed: a file://, ftp:// or other location is not a storage link.
        ensure(
            location.startswith(("https://", "http://")), lambda: unavailable(ValueError(location))
        )
        chunks: list[bytes] = []
        total = 0
        try:
            # No Authorization header: the URL is presigned (and storage refuses two auths).
            async with self._client.stream("GET", location) as stored:
                status = stored.status_code
                ensure(stored.is_success, lambda: refused(status, ErrorCode.ContentEmpty, "File"))
                async for chunk in stored.aiter_bytes():
                    total += len(chunk)
                    self._within_limit(total)
                    chunks.append(chunk)
        except httpx2.HTTPError as error:
            match_error(error, {httpx2.HTTPError: unavailable})
        ensure(total > 0, ErrorCode.ContentEmpty, "The asset has no content")
        return b"".join(chunks)

    async def model_trace(self, caller: Caller, entity_id: UUID) -> tuple[UUID, Asset]:
        """The ``thumbnail`` validation result of ``entity_id`` and its PNG asset."""
        page = await self._json(
            caller,
            f"/{EntityRoute.ValidationResult}",
            params={"name": THUMBNAIL_VALIDATION, "validated_entity_id": str(entity_id)},
            what="Validation result",
            not_found=ErrorCode.ValidationResultNotFound,
        )
        rows = self._parsed(lambda: list(page["data"]))
        first = require(
            next(iter(rows), None),
            ErrorCode.ValidationResultNotFound,
            "No thumbnail validation result for this entity",
        )
        result_id = self._parsed(lambda: UUID(first["id"]))
        listing = await self._json(
            caller, f"/{EntityRoute.ValidationResult}/{result_id}/assets", what="Asset"
        )
        assets = self._parsed(lambda: [asset_of(row) for row in listing["data"]])
        png = require(
            next((a for a in assets if a.content_type == MODEL_TRACE_MEDIA_TYPE), None),
            ErrorCode.AssetNotFound,
            "The validation result has no PNG asset",
        )
        return result_id, png

    async def _json(
        self,
        caller: Caller,
        path: str,
        *,
        what: str,
        params: Mapping[str, str] | None = None,
        not_found: ErrorCode = ErrorCode.AssetNotFound,
    ) -> Any:  # noqa: ANN401 - JSON
        response = await self._send(caller, path, params=params)
        ensure(response.is_success, lambda: refused(response.status_code, not_found, what))
        return self._parsed(response.json)

    async def _send(
        self, caller: Caller, path: str, *, params: Mapping[str, str] | None = None
    ) -> httpx2.Response:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {caller.token}"}
        if caller.virtual_lab_id:
            headers["virtual-lab-id"] = str(caller.virtual_lab_id)
        if caller.project_id:
            headers["project-id"] = str(caller.project_id)
        started = time.perf_counter()
        try:
            response = await self._client.get(f"{self._base}{path}", headers=headers, params=params)
        except httpx2.HTTPError as error:
            match_error(error, {httpx2.HTTPError: unavailable})
        log.debug(
            "http request",
            path=path,  # never the query string or a redirect location: they can carry data
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    def _within_limit(self, size: int) -> None:
        ensure(
            size <= self._max,
            ErrorCode.AssetTooLarge,
            "The asset is too large to draw",
            limit=self._max,
        )

    @staticmethod
    def _parsed[T](read: Callable[[], T]) -> T:
        """``read()``; an answer of the wrong shape means entitycore is not what we expect."""
        try:
            return read()
        except (KeyError, TypeError, ValueError) as error:
            return match_error(
                error, {KeyError: unavailable, TypeError: unavailable, ValueError: unavailable}
            )
