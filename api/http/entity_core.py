"""
Module: entity_core.py

This module provides functionality for interacting with the Entity Core service,
handling asset management and retrieval operations for assets.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum, StrEnum, auto
from typing import Annotated, Any, Dict, List, Literal, Optional, Union, overload
from urllib.parse import urljoin

import httpx
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger as L
from pydantic import BaseModel

from api.exceptions import ContentEmpty
from api.settings import settings


class EntityType(StrEnum):
    """Entity types supported in the API."""

    @staticmethod
    def _generate_next_value_(name, start, count, last_values) -> str:
        return name.replace("_", "-")

    emodel = auto()
    experimental_bouton_density = auto()
    experimental_neuron_density = auto()
    experimental_synapses_per_connection = auto()
    mesh = auto()
    reconstruction_morphology = auto()
    electrical_cell_recording = auto()
    single_neuron_simulation = auto()
    single_neuron_synaptome = auto()
    single_neuron_synaptome_simulation = auto()
    validation_result = auto()


class AssetStatus(str, Enum):
    """Status of an asset."""

    CREATED = "CREATED"
    DELETED = "DELETED"


class ProjectContext(BaseModel):
    """Request context containing authentication and identification information."""

    virtual_lab_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None


class AssetBase(BaseModel):
    """Asset model with common attributes."""

    path: str
    full_path: str
    # bucket_name: str
    is_directory: bool
    content_type: str
    size: int
    sha256_digest: Optional[str] = None
    meta: Dict[str, Any]


class AssetRead(AssetBase):
    """Asset model for responses."""

    id: uuid.UUID
    status: str


class ValidationResult(BaseModel):
    id: uuid.UUID
    name: str
    passed: bool
    validated_entity_id: uuid.UUID
    creation_date: datetime
    update_date: datetime

    class Config:
        from_attributes = True


class PaginationResponse(BaseModel):
    """Pagination metadata."""

    page: int
    page_size: int
    total_items: int


class ListResponse[T](BaseModel):
    """List response with pagination."""

    data: List[T]
    pagination: PaginationResponse


ProjectContextDep = Annotated[ProjectContext, Header()]
AuthDep = Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer(auto_error=False))]


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

    def _get_headers(
        self, context: ProjectContext, token: HTTPAuthorizationCredentials
    ) -> Dict[str, str]:
        """Get headers for the request.

        Args:
            context: Request context containing auth and identification info

        Returns:
            Dictionary of headers
        """
        headers = {"Accept": "application/json"}

        if token:
            headers["Authorization"] = f"Bearer {token.credentials}"

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
        context: ProjectContext,
        token: HTTPAuthorizationCredentials,
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
            headers=self._get_headers(context, token),
        )
        response.raise_for_status()
        parsed = response.json()
        return ListResponse[AssetRead](
            data=[AssetRead.model_validate(item) for item in parsed["data"]],
            pagination=PaginationResponse.model_validate(parsed["pagination"]),
        )

    async def get_entity_asset(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        asset_id: uuid.UUID,
        context: ProjectContext,
        token: HTTPAuthorizationCredentials,
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
            headers=self._get_headers(context, token),
        )
        response.raise_for_status()
        return AssetRead.model_validate(response.json())

    async def get_asset_download_url(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        asset_id: uuid.UUID,
        context: ProjectContext,
        token: HTTPAuthorizationCredentials,
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
        url = self._build_url(f"{entity_type}/{entity_id}/assets/{asset_id}/download")

        response = await self._client.get(
            url,
            headers=self._get_headers(context, token),
            follow_redirects=False,
        )

        if response.status_code in (301, 302, 303, 307, 308):
            return response.headers.get("location")
        raise ContentEmpty("Download url can not be extracted")

    @overload
    async def get_asset_content(self, url: str, as_type: Literal["bytes"]) -> bytes: ...

    @overload
    async def get_asset_content(self, url: str, as_type: Literal["str"]) -> str: ...

    @overload
    async def get_asset_content(self, url: str) -> bytes: ...

    async def get_asset_content(
        self, url: str, as_type: Literal["bytes", "str"] = "bytes"
    ) -> Union[bytes, str]:
        """Get the content of an asset from its URL.

        Args:
            url: URL of the asset
            as_type: Expected content type, either 'bytes' or 'str'

        Returns:
            Content of the asset as bytes or str

        Raises:
            ContentEmpty: If the content cannot be retrieved
        """
        response = await self._client.get(url)
        response.raise_for_status()

        if as_type == "str":
            file_content = response.text
        else:
            file_content = response.content

        if not file_content:
            raise ContentEmpty()

        return file_content

    async def get_validation_results(
        self,
        *,
        name: str,
        validated_entity_id: uuid.UUID,
        context: ProjectContext,
        token: HTTPAuthorizationCredentials,
    ):
        url = self._build_url("validation-result")

        response = await self._client.get(
            url,
            headers=self._get_headers(context, token),
            params={"name": name, "validated_entity_id": str(validated_entity_id)},
            follow_redirects=False,
        )
        response.raise_for_status()

        parsed = response.json()
        return ListResponse[ValidationResult](
            data=[ValidationResult.model_validate(item) for item in parsed["data"]],
            pagination=PaginationResponse.model_validate(parsed["pagination"]),
        )


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
