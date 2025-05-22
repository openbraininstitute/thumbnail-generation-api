# pylint: disable=duplicate-code
"""
Module: ephys.py

This module provides functionality for generating ephys previews
"""

import io
import uuid
from dataclasses import dataclass
from http import HTTPStatus as status
from typing import Optional

import h5py
import matplotlib.pyplot as plt
import numpy as np
from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPBearer
from loguru import logger as L
from numpy.typing import NDArray

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import ContentEmpty
from api.http.entity_core import (
    EntityType,
    RequestContext,
    get_entitycore_client,
    get_request_context,
)
from api.models.enums import MetaType
from api.tools.plot_ephys import plot_nwb_ephys
from api.utils.common import get_buffer
from api.utils.trace_img import (
    get_conversion,
    get_rate,
    get_unit,
    select_element,
    select_protocol,
    select_response,
)


@dataclass
class EphysData:
    """Container for ephys data and its metadata."""

    data: NDArray
    unit: str
    rate: float


router = APIRouter(
    prefix="/electrical-cell-recording",
)
require_bearer = HTTPBearer()


async def get_ephys_content(
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    context: RequestContext = Depends(get_request_context),
):
    """Get the ephys file content from the entity core service."""
    async with get_entitycore_client() as core_client:
        download_url = await core_client.get_asset_download_url(
            entity_type=EntityType.electrical_cell_recording,
            entity_id=entity_id,
            asset_id=asset_id,
            context=context,
        )
        return await core_client.get_asset_content(download_url)


def extract_ephys_data(ephys_file: bytes) -> EphysData:
    """Extract data from the ephys HDF5 file."""
    # pylint: disable-msg=too-many-locals
    with h5py.File(io.BytesIO(ephys_file), "r") as h5_handle:
        try:
            # LNMC-complient format containing data organization hierarchy
            data_org_group = h5_handle["data_organization"]

            cell_key = select_element(list(data_org_group.keys()), n=0)
            cell_group = data_org_group[cell_key]

            protocol_key = select_protocol(list(cell_group.keys()))
            protocol_group = cell_group[protocol_key]

            repetition_key = select_element(
                list(protocol_group.keys()), n=0, meta=MetaType.REPETITION
            )
            repetition_group = protocol_group[repetition_key]

            sweep_key = select_element(
                list(repetition_group.keys()), n=-3, meta=MetaType.SWEEP
            )
            sweep_group = repetition_group[sweep_key]

            response_key = select_response(list(sweep_group.keys()))
            response_group = sweep_group[response_key]
        except KeyError:
            # Generic format
            acquisition_group = h5_handle["acquisition"]

            response_key = select_element(list(acquisition_group.keys()), n=-3)
            response_group = acquisition_group[response_key]

        # Get relevant data, unit, rate, and conversion factor
        unit = get_unit(response_group)
        rate = get_rate(response_group)
        conversion = get_conversion(response_group)

        # Retrieve and process the data
        data = np.array(response_group["data"][:]) * conversion

        return EphysData(data=data, unit=unit, rate=rate)


def generate_plot(ephys_data: EphysData, dpi: Optional[int]) -> bytes:
    """Generate a plot from the ephys data."""
    try:
        fig = plot_nwb_ephys(ephys_data.data, ephys_data.unit, ephys_data.rate)
        buffer = get_buffer(fig, dpi)
        return buffer.getvalue()
    except Exception as ex:
        raise ApiError(
            message=f"Error while converting asset to buffer: {ex}",
            error_code=ApiErrorCode.BUFFERING_ERROR,
            http_status_code=status.BAD_REQUEST,
        ) from ex
    finally:
        plt.close(fig)


@router.get(
    "/preview",
    dependencies=[Depends(require_bearer)],
    response_model=None,
)
async def get_ephys_preview(
    entity_id: uuid.UUID,
    asset_id: uuid.UUID,
    dpi: Optional[int] = Query(None, ge=10, le=600),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    """
    Generate a preview of an ephys trace.

    Args:
        entity_id: The ID of the entity
        asset_id: The ID of the asset
        dpi: The DPI of the preview
        context: The context of the request

    Returns:
        A response containing the preview of the ephys trace
    """
    try:
        # Get the ephys file content
        ephys_file = await get_ephys_content(entity_id, asset_id, context)

        # Extract data from the file
        ephys_data = extract_ephys_data(ephys_file)

        # Generate the plot
        image_bytes = generate_plot(ephys_data, dpi)

        return Response(image_bytes, media_type="image/png")
    except ContentEmpty as ex:
        L.error(f"ContentEmpty error while getting ephys preview: {ex}")
        raise ApiError(
            message=str(ex),
            error_code=ApiErrorCode.ASSET_NOT_FOUND,
            http_status_code=status.NOT_FOUND,
        ) from ex
    except Exception as ex:
        L.error(f"Server error while getting ephys preview: {ex}")
        raise ApiError(
            message=str(ex),
            error_code=ApiErrorCode.INTERNAL_ERROR,
            http_status_code=status.INTERNAL_SERVER_ERROR,
        ) from ex
