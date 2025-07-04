"""
Module: morphology.py

This module provides functionality for generating simulation plot previews
"""

import uuid
from enum import StrEnum
from http import HTTPStatus as status
from typing import Literal, Optional, cast

from fastapi import APIRouter, HTTPException, Response
from fastapi.security import HTTPBearer
from loguru import logger as L

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import ContentEmpty
from api.http.entity_core import (
    AuthDep,
    EntityType,
    ProjectContextDep,
    get_entitycore_client,
)
from api.models.common import PlotTarget
from api.services.simulation_img import generate_simulation_plots

router = APIRouter()
require_bearer = HTTPBearer()


class SimulationType(StrEnum):
    single_neuron_synaptome = EntityType.single_neuron_simulation.value
    single_neuron_synaptome_simulation = (
        EntityType.single_neuron_synaptome_simulation.value
    )


@router.get(
    "/{simulation_type}/preview",
)
async def get_simulation_plot(
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    simulation_type: Literal[
        EntityType.single_neuron_simulation,
        EntityType.single_neuron_synaptome_simulation,
    ],
    target: PlotTarget,
    context: ProjectContextDep,
    auth: AuthDep,
    w: Optional[int] = None,
    h: Optional[int] = None,
) -> Response:
    """
    Generate a preview of a simulation

    Args:
        entity_id: The ID of the entity
        asset_id: The ID of the asset
        simulation_type: Type of simulation
        target: Plot target
        w: Width of the generated image
        h: Height of the generated image
        context: The context of the request

    Returns:
        A response containing the plot of the simulation target
    """

    try:
        async with get_entitycore_client() as core_client:
            L.info(f"{context}")

            download_url = await core_client.get_asset_download_url(
                entity_type=cast(EntityType, simulation_type),
                entity_id=entity_id,
                asset_id=asset_id,
                context=context,
                token=auth,
            )

            L.info(
                f"download_url: {download_url}",
            )
            simulation_file = await core_client.get_asset_content(
                download_url, as_type="str"
            )

            image = generate_simulation_plots(
                config_file_content=simulation_file,
                w=w,
                h=h,
                target=target,
            )
            if image is None:
                raise HTTPException(
                    status_code=status.NOT_FOUND,
                    detail="Simulation results data not found",
                )
        return Response(image, media_type="image/png")
    except ValueError as exc:
        raise HTTPException(
            status.BAD_GATEWAY, "Simulation config file is malformed"
        ) from exc
    except ContentEmpty as ex:
        L.error(f"ContentEmpty error while getting morphology preview: {ex}")
        raise ApiError(
            message=ex.detail.get("message") or "Content is not available",
            details=ex,
            error_code=ApiErrorCode.ASSET_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except Exception as exc:
        raise HTTPException(
            status.INTERNAL_SERVER_ERROR, "Internal server error"
        ) from exc
