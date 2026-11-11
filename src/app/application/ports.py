"""The external system this service needs, as a port (Ports and Adapters, spec 06 C-L4).

``infrastructure/entitycore.py`` implements it over HTTP; tests pass an in-memory fake.
"""

from typing import Protocol
from uuid import UUID

from app.domain.preview import Asset, Caller, EntityRoute


class EntityCore(Protocol):
    """Reads assets as the caller: entitycore decides what the caller may read.

    Every method raises ``DomainError`` with ``UNAUTHENTICATED``, ``FORBIDDEN``,
    ``ASSET_NOT_FOUND`` (entitycore's answer for "missing or not readable by you"),
    ``ASSET_NOT_READY`` or ``ENTITYCORE_UNAVAILABLE``.
    """

    async def asset(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset_id: UUID
    ) -> Asset:
        """The asset's metadata (size, sha256), read with the caller's token."""
        ...

    async def content(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset: Asset
    ) -> bytes:
        """The asset's bytes (``ASSET_TOO_LARGE`` over the limit, ``CONTENT_EMPTY`` if none)."""
        ...

    async def model_trace(self, caller: Caller, entity_id: UUID) -> tuple[UUID, Asset]:
        """The validation result named ``thumbnail`` of ``entity_id`` and its PNG asset.

        Raises ``VALIDATION_RESULT_NOT_FOUND`` or ``ASSET_NOT_FOUND`` when either is missing.
        """
        ...
