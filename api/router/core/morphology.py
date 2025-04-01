# pylint: disable=duplicate-code

"""
Module: morphology.py

This module provides functionality for generating morphology previews
"""

import io
import uuid
from http import HTTPStatus as status
from typing import Optional

import matplotlib.pyplot as plt
import neurom as nm
from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPBearer
from loguru import logger as L

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import ContentEmpty
from api.http.entity_core import (
    EntityType,
    RequestContext,
    get_entitycore_client,
    get_request_context,
)
from api.tools.plot_morphology import plot_morphology
from api.utils.common import get_buffer

router = APIRouter(
    prefix="/reconstruction-morphology",
)
require_bearer = HTTPBearer()


@router.get(
    "/preview",
    dependencies=[Depends(require_bearer)],
    response_model=None,
)
async def get_morphology_preview(
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    dpi: Optional[int] = Query(None, ge=10, le=600),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    """
    Generate a preview of a morphology

    Args:
        entity_id: The ID of the entity
        asset_id: The ID of the asset
        dpi: The DPI of the preview
        context: The context of the request

    Returns:
        A response containing the preview of the morphology
    """
    morphology_file = None
    try:
        async with get_entitycore_client() as core_client:
            download_url = await core_client.download_entity_asset(
                entity_type=EntityType.RECONSTRUCTION_MORPHOLOGY,
                entity_id=entity_id,
                asset_id=asset_id,
                context=context,
            )
            morphology_file = await core_client.get_asset_content(download_url)

        # Load the morphology from the downloaded content
        morphology = nm.load_morphology(io.StringIO(morphology_file), reader="swc")

        try:
            # Generate the buffer for the image
            fig = plot_morphology(morphology)
            buffer = get_buffer(fig, dpi)

            # Convert buffer to bytes
            image_bytes = buffer.getvalue()
        except Exception as ex:
            raise ApiError(
                message=f"Error while converting asset to buffer: {ex}",
                error_code=ApiErrorCode.BUFFERING_ERROR,
                http_status_code=status.BAD_REQUEST,
            ) from ex
        finally:
            # Explicitly close the figure to release memory
            plt.close(fig)

        return Response(image_bytes, media_type="image/png")
    except ContentEmpty as ex:
        L.error(f"ContentEmpty error while getting morphology preview: {ex}")
        raise ApiError(
            message=str(ex),
            error_code=ApiErrorCode.ASSET_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except Exception as ex:
        L.error(f"Server error while getting morphology preview: {ex}")
        raise ApiError(
            message=str(ex),
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=status.INTERNAL_SERVER_ERROR,
        ) from ex
