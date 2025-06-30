# pylint: disable=duplicate-code

"""
Module: morphology.py

This module provides functionality for generating morphology previews
"""

import uuid
from http import HTTPStatus as status

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPBearer
from loguru import logger as L

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import AssetNotFound, ContentEmpty, ValidationResultNotFound
from api.http.entity_core import (
    AuthDep,
    EntityType,
    ProjectContextDep,
    get_entitycore_client,
)

router = APIRouter(
    prefix="/model-trace",
)
require_bearer = HTTPBearer()


@router.get(
    "/preview",
    dependencies=[Depends(require_bearer)],
    response_model=None,
)
async def get_model_trace_preview(
    entity_id: uuid.UUID,
    context: ProjectContextDep,
    auth: AuthDep,
) -> Response:
    """
    Generate a preview of a model trace

    Args:
        entity_id: The ID of the entity
        context: The context of the request

    Returns:
        A response containing the preview of the model trace
    """
    try:
        async with get_entitycore_client() as core_client:
            results = await core_client.get_validation_results(
                name="thumbnail",
                validated_entity_id=entity_id,
                context=context,
                token=auth,
            )
            if not results or not results.data:
                raise ValidationResultNotFound()

            L.debug("validation_results:\n{}", results)
            assets = await core_client.get_entity_assets(
                entity_type=EntityType.validation_result,
                entity_id=results.data[0].id,
                context=context,
                token=auth,
            )
            L.debug("assets:\n{}", assets.data)
            asset = next(
                (asset for asset in assets.data if asset.content_type == "image/png"),
                None,
            )
            if not asset:
                raise AssetNotFound()

            download_url = await core_client.get_asset_download_url(
                entity_type=EntityType.validation_result,
                entity_id=results.data[0].id,
                asset_id=asset.id,
                context=context,
                token=auth,
            )
            if not download_url:
                raise ContentEmpty()

            thumbnail_file = await core_client.get_asset_content(
                download_url, as_type="bytes"
            )
            return Response(thumbnail_file, media_type=asset.content_type)

    except ValidationResultNotFound as ex:
        L.error(
            f"ValidationResultNotFound error while getting model trace preview: {ex}"
        )
        raise ApiError(
            message=ex.detail.get("message") or "Validation result not found",
            details=ex,
            error_code=ApiErrorCode.VALIDATION_RESULT_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except AssetNotFound as ex:
        L.error(f"AssetNotFound error while getting model trace preview: {ex}")
        raise ApiError(
            message=ex.detail.get("message") or "Asset not found",
            details=ex,
            error_code=ApiErrorCode.ASSET_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except ContentEmpty as ex:
        L.error(f"ContentEmpty error while getting model trace preview: {ex}")
        raise ApiError(
            message=ex.detail.get("message") or "Content empty",
            details=ex,
            error_code=ApiErrorCode.CONTENT_EMPTY,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except Exception as ex:
        L.error(f"Server error while getting model trace preview: {ex}")
        L.exception(ex)
        raise ApiError(
            message="Internal server error",
            details=str(ex),
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=status.INTERNAL_SERVER_ERROR,
        ) from ex
