"""
Module: entity_core.py

This module provides functionality for interacting with the Entity Core service,
handling asset management and retrieval operations for assets.
"""

import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Dict, List, Optional, cast
from urllib.parse import urljoin

import httpx
from fastapi import Header, Request
from loguru import logger as L
from pydantic import BaseModel

from api.exceptions import ContentEmpty
from api.settings import settings


class EntityType(str, Enum):
    """Entity types supported in the API."""

    EMODEL = "emodel"
    EXPERIMENTAL_BOUTON_DENSITY = "experimental-bouton-density"
    EXPERIMENTAL_NEURON_DENSITY = "experimental-neuron-density"
    EXPERIMENTAL_SYNAPSES_PER_CONNECTION = "experimental-synapses-per-connection"
    MESH = "mesh"
    RECONSTRUCTION_MORPHOLOGY = "reconstruction-morphology"
    SINGLE_CELL_EXPERIMENTAL_TRACE = "single-cell-experimental-trace"


class AssetStatus(str, Enum):
    """Status of an asset."""

    CREATED = "CREATED"
    DELETED = "DELETED"


class RequestContext(BaseModel):
    """Request context containing authentication and identification information."""

    auth_token: Optional[str] = None
    virtual_lab_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None


class AssetBase(BaseModel):
    """Asset model with common attributes."""

    path: str
    full_path: str
    bucket_name: str
    is_directory: bool
    content_type: str
    size: int
    sha256_digest: Optional[str] = None
    meta: Dict[str, Any]


class AssetRead(AssetBase):
    """Asset model for responses."""

    id: uuid.UUID
    status: AssetStatus


class PaginationResponse(BaseModel):
    """Pagination metadata."""

    page: int
    page_size: int
    total_items: int


class ListResponse(BaseModel):
    """List response with pagination."""

    data: List[AssetRead]
    pagination: PaginationResponse


class EntityCoreClient:
    """Client for interacting with asset endpoints."""

    def __init__(
        self,
        base_url: str,
    ):
        """Initialize the asset client.

        Args:
            base_url: Base URL of the API
        """
        self.base_url = base_url.rstrip("/") + "/"
        self._client = httpx.AsyncClient()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close the httpx client session."""
        await self._client.aclose()

    def _get_headers(self, context: RequestContext) -> Dict[str, str]:
        """Get headers for the request.

        Args:
            context: Request context containing auth and identification info

        Returns:
            Dictionary of headers
        """
        headers = {"Accept": "application/json"}

        if context.auth_token:
            headers["Authorization"] = f"Bearer {context.auth_token}"

        if context.virtual_lab_id:
            headers["virtual-lab-id"] = str(context.virtual_lab_id)
        if context.project_id:
            headers["project-id"] = str(context.project_id)

        return headers

    def _build_url(self, endpoint: str) -> str:
        """Build the full URL for the endpoint."""
        return urljoin(self.base_url, endpoint)

    async def get_entity_assets(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        context: RequestContext,
    ) -> ListResponse:
        """Get all assets for an entity.

        Args:
            entity_type: Type of the entity
            entity_id: ID of the entity
            context: Request context containing auth and identification info

        Returns:
            List of assets
        """
        url = self._build_url(f"{entity_type.value}/{entity_id}/assets")

        response = await self._client.get(
            url,
            headers=self._get_headers(context),
        )
        response.raise_for_status()
        return ListResponse.model_validate(response.json())

    async def get_entity_asset(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        asset_id: uuid.UUID,
        context: RequestContext,
    ) -> AssetRead:
        """Get a specific asset for an entity.

        Args:
            entity_type: Type of the entity
            entity_id: ID of the entity
            asset_id: ID of the asset
            context: Request context containing auth and identification info

        Returns:
            Asset metadata
        """
        url = self._build_url(f"{entity_type.value}/{entity_id}/assets/{asset_id}")

        response = await self._client.get(
            url,
            headers=self._get_headers(context),
        )
        response.raise_for_status()
        return AssetRead.model_validate(response.json())

    async def get_asset_download_url(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        asset_id: uuid.UUID,
        context: RequestContext,
    ) -> str:
        """Get a download URL for an asset.

        Args:
            entity_type: Type of the entity
            entity_id: ID of the entity
            asset_id: ID of the asset
            context: Request context containing auth and identification info

        Returns:
            Presigned URL for downloading the asset

        Raises:
            ContentEmpty: If the download URL cannot be extracted
        """
        url = self._build_url(f"{entity_type.value}/{entity_id}/assets/{asset_id}/download")

        response = await self._client.get(
            url,
            headers=self._get_headers(context),
            follow_redirects=False,
        )

        if response.status_code in (301, 302, 303, 307, 308):
            return response.headers.get("location")
        raise ContentEmpty("Download url can not be extracted")

    async def get_asset_content(self, url: str) -> str:
        """Get the content of an asset from its URL.

        Args:
            url: URL of the asset

        Returns:
            Content of the asset as a string

        Raises:
            ContentEmpty: If the content cannot be retrieved
        """
        response = await self._client.get(url)
        response.raise_for_status()
        file_content = response.text

        if file_content is None:
            raise ContentEmpty()
        return cast(str, file_content)


@asynccontextmanager
async def get_entitycore_client():
    """Get an instance of the EntityCoreClient.

    This context manager creates and manages the lifecycle of an EntityCoreClient instance.

    Yields:
        EntityCoreClient: An instance of the client
    """
    L.info("entity_core_uri:", settings.entity_core_uri)
    async with EntityCoreClient(settings.entity_core_uri) as client:
        yield client


async def get_entitycore_client_dependency() -> EntityCoreClient:
    """FastAPI dependency that returns an EntityCoreClient instance.

    Returns:
        EntityCoreClient: The client instance
    """
    client = EntityCoreClient(
        base_url=settings.entity_core_uri,
    )
    return client


# Define a dependency to extract authorization and context from request headers
async def get_request_context(
    request: Request,
    virtual_lab_id: Optional[str] = Header(None),
    project_id: Optional[str] = Header(None),
) -> Dict[str, Optional[str]]:
    """Get the context from the request headers.

    Args:
        request: The FastAPI request object
        virtual_lab_id: Optional virtual lab ID from header
        project_id: Optional project ID from header

    Returns:
        Dictionary containing auth_token, virtual_lab_id, and project_id
    """
    auth_header = request.headers.get("Authorization", "")
    auth_token = auth_header.replace("Bearer ", "") if auth_header else None

    return RequestContext(
        auth_token=auth_token,
        virtual_lab_id=virtual_lab_id,
        project_id=project_id,
    )
