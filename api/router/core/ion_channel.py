# pylint: disable=duplicate-code
"""
Module: ion_channel.py

This module provides functionality for generating ion-channel-recording previews
"""

import io
import uuid
from http import HTTPStatus as status  # noqa: N813
from typing import cast

import h5py
import matplotlib.pyplot as plt
import numpy as np
from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPBearer
from loguru import logger as L  # noqa: N812

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import ContentEmpty
from api.http.entity_core import (
    AuthDep,
    EntityType,
    HTTPAuthorizationCredentials,
    ProjectContext,
    ProjectContextDep,
    get_entitycore_client,
)
from api.tools.plot_ion_channel import plot_nwb_ion_channel
from api.types import IonChannelRecordingData
from api.utils.common import get_buffer

router = APIRouter(
    prefix="/ion-channel-recording",
)
require_bearer = HTTPBearer()


async def get_ion_channel_recording_content(
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    context: ProjectContext,
    token: HTTPAuthorizationCredentials,
):
    """Get the ion_channel_recording file content from the entity core service."""
    async with get_entitycore_client() as core_client:
        download_url = await core_client.get_asset_download_url(
            entity_type=EntityType.ion_channel_recording,
            entity_id=entity_id,
            asset_id=asset_id,
            context=context,
            token=token,
        )
        return await core_client.get_asset_content(download_url)


def extract_ion_channel_recording_data(
    ion_channel_recording_file: bytes,
) -> IonChannelRecordingData:
    """Extract data from the ion_channel_recording HDF5 file."""
    # pylint: disable-msg=too-many-locals
    with h5py.File(io.BytesIO(ion_channel_recording_file), "r") as h5_handle:
        try:
            acquisition_group = cast("dict", h5_handle["acquisition"])
            timeseries_group = cast("dict", acquisition_group["timeseries"])
            activation_group = cast("dict", timeseries_group["Activation"])
            activation_repetitions_group = cast("dict", activation_group["repetitions"])
            activation_repetition1_group = cast("dict", activation_repetitions_group["repetition1"])
        except KeyError as ex:
            raise ApiError(
                message="Error while parsing nwb file!",
                details=ex,
                error_code=ApiErrorCode.BUFFERING_ERROR,
                http_status_code=status.INTERNAL_SERVER_ERROR,
            ) from ex

        activation_current = np.asarray(activation_repetition1_group["data"], dtype=np.float32)
        activation_dt = np.asarray(activation_repetition1_group["x_interval"], dtype=np.float32)

        return IonChannelRecordingData(
            activation_current=activation_current,
            activation_dt=activation_dt,
        )


def generate_plot(ion_channel_recording_data: IonChannelRecordingData, dpi: int | None) -> bytes:
    """Generate a plot from the ion_channel_recording data."""
    fig = None
    try:
        fig = plot_nwb_ion_channel(ion_channel_recording_data)
        buffer = get_buffer(fig, dpi)
        return buffer.getvalue()
    except Exception as ex:
        raise ApiError(
            message="Error while converting asset to buffer",
            details=ex,
            error_code=ApiErrorCode.BUFFERING_ERROR,
            http_status_code=status.BAD_REQUEST,
        ) from ex
    finally:
        if fig:
            plt.close(fig)


@router.get(
    "/preview",
    dependencies=[Depends(require_bearer)],
    response_model=None,
)
async def get_ion_channel_recording_preview(
    context: ProjectContextDep,
    auth: AuthDep,
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    dpi: int | None = Query(None, ge=10, le=600),
) -> Response:
    """
    Generate a preview of an ion_channel_recording trace.

    Args:
        entity_id: The ID of the entity
        asset_id: The ID of the asset
        dpi: The DPI of the preview
        context: The context of the request

    Returns:
        A response containing the preview of the ion_channel_recording trace
    """
    try:
        # Get the ion_channel_recording file content
        ion_channel_recording_file = await get_ion_channel_recording_content(
            entity_id, asset_id, context, auth
        )

        # Extract data from the file
        ion_channel_recording_data = extract_ion_channel_recording_data(ion_channel_recording_file)

        # Generate the plot
        image_bytes = generate_plot(ion_channel_recording_data, dpi)

        return Response(image_bytes, media_type="image/png")
    except ContentEmpty as ex:
        L.error(f"ContentEmpty error while getting ion_channel_recording preview: {ex}")
        raise ApiError(
            message="Error while getting ion_channel_recording preview",
            details=ex,
            error_code=ApiErrorCode.ASSET_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except Exception as ex:
        L.error(f"Server error while getting ion_channel_recording preview: {ex}")
        raise ApiError(
            message="Error while getting ion_channel_recording preview",
            details=ex,
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=status.INTERNAL_SERVER_ERROR,
        ) from ex
