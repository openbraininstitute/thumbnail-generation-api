"""The entitycore port (Ports and Adapters); ``infrastructure/entitycore.py`` implements it."""

from typing import Protocol
from uuid import UUID

from app.domain.preview import Asset, Caller, EntityRoute


class EntityCore(Protocol):
    """Reads assets as the caller; entitycore decides access.

    Every method may raise ``DomainError``: ``UNAUTHENTICATED``, ``FORBIDDEN``,
    ``ASSET_NOT_FOUND``, ``ASSET_NOT_READY`` or ``ENTITYCORE_UNAVAILABLE``.
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
        """The ``thumbnail`` validation result of ``entity_id`` and its PNG asset."""
        ...
