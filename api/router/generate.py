"""
Module: generate.py

This module defines a FastAPI router for handling requests related to morphology images.
It includes an endpoint to get a preview image of a morphology.
"""

from http import HTTPStatus as status

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer

from api.dependencies import retrieve_user
from api.models.common import (
    ErrorMessage,
    ImageGenerationInput,
    SimulationGenerationInput,
)
from api.services.morpho_img import generate_morphology_image
from api.services.nexus import fetch_file_content
from api.services.simulation_img import generate_simulation_plots
from api.services.trace_img import generate_electrophysiology_image
from api.user import User

router = APIRouter()
require_bearer = HTTPBearer()


@router.get(
    "/morphology-image",
    dependencies=[Depends(require_bearer)],
    responses={404: {"model": ErrorMessage}, 422: {"model": ErrorMessage}},
    response_model=None,
)
def get_morphology_image(
    image_input: ImageGenerationInput = Depends(), user: User = Depends(retrieve_user)
) -> Response:
    """
    Endpoint to get a preview image of a morphology.
    Sample Content URL:
    https://bbp.epfl.ch/nexus/v1/files/bbp/mouselight/https%3A%2F%2Fbbp.epfl.ch%2Fnexus%2Fv1%2Fresources%2Fbbp%2Fmouselight%2F_%2F0befd25c-a28a-4916-9a8a-adcd767db118
    """
    image = generate_morphology_image(
        access_token=user.access_token,
        content_url=image_input.content_url,
        dpi=image_input.dpi,
    )

    return Response(image, media_type="image/png")


@router.get(
    "/trace-image",
    dependencies=[Depends(require_bearer)],
    responses={404: {"model": ErrorMessage}},
    response_model=None,
)
def get_trace_image(
    image_input: ImageGenerationInput = Depends(), user: User = Depends(retrieve_user)
) -> Response:
    """
    Endpoint to get a preview image of an electrophysiology trace
    Sample Content URL:
    https://bbp.epfl.ch/nexus/v1/files/public/hippocampus/https%3A%2F%2Fbbp.epfl.ch%2Fneurosciencegraph%2Fdata%2Fb67a2aa6-d132-409b-8de5-49bb306bb251
    """
    image = generate_electrophysiology_image(
        access_token=user.access_token,
        content_url=image_input.content_url,
        dpi=image_input.dpi,
    )

    return Response(image, media_type="image/png")


@router.get(
    "/simulation-plot",
    dependencies=[Depends(require_bearer)],
    responses={404: {"model": ErrorMessage}},
    response_model=None,
)
def get_simulation_plot(
    config: SimulationGenerationInput = Depends(), user: User = Depends(retrieve_user)
) -> Response:
    """
    Endpoint to get a preview image of an simulation plots
    Sample Content URL:
    https://sbo-nexus-delta.shapes-registry.org/v1/files/cad43d74-f697-48d6-9242-28cb6b4a4956/f9b265b2-22c3-4a92-9ad5-79dff37e39ca/https%3A%2F%2Fopenbrainplatform.org%2Fdata%2Fcad43d74-f697-48d6-9242-28cb6b4a4956%2Ff9b265b2-22c3-4a92-9ad5-79dff37e39ca%2Feadf0aa4-109c-4422-806c-325e5669565a?rev=1
    """

    response = fetch_file_content(user.access_token, config.content_url).decode(
        encoding="utf-8"
    )

    try:
        image = generate_simulation_plots(
            config_file_content=response,
            w=config.w,
            h=config.h,
            target=config.target,
        )
        if image is None:
            raise HTTPException(
                status_code=status.NOT_FOUND, detail="Simulation results data not found"
            )
        return Response(image, media_type="image/png")
    except ValueError as exc:
        raise HTTPException(
            status.BAD_GATEWAY, "Simulation config file is malformed"
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status.INTERNAL_SERVER_ERROR, "Internal server error"
        ) from exc
