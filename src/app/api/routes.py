"""The preview routes, ``/core/{entity}/preview``, called by core-web-app and neuroagent-ts.

Do not rename functions, paths or parameters: neuroagent-ts names its generated types after the
operation ids (``tests/api/test_openapi.py`` checks them). nginx caches each image, so these run
only on a cache miss; the browser keeps it an hour (``private``), then revalidates with the ETag.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.api.problems import RESPONSES
from app.application.previews import Plan, Previews, is_current
from app.domain.errors import ErrorCode
from app.domain.guards import require
from app.domain.preview import (
    Caller,
    EntityRoute,
    ImageFormat,
    PlotTarget,
    RenderSpec,
)

CACHE_CONTROL = "private, max-age=3600"
# nginx keeps a model trace 1 h, not 30 d: its key has no asset id, and a re-run adds a new trace.
MODEL_TRACE_NGINX_SECONDS = 3600
MAX_PIXELS_SIDE = 4096  # a simulation plot side; bounds what one request can make kaleido draw

IMAGE = {  # the 200 answer: an image in the asked format (png by default)
    200: {
        "description": "The image",
        "content": {
            "image/png": {"schema": {"type": "string", "format": "binary"}},
            "image/webp": {"schema": {"type": "string", "format": "binary"}},
        },
    },
    304: {"description": "Not modified: the caller's copy (If-None-Match) is current"},
}

# default_response_class=Response: the routes answer images, so OpenAPI lists no JSON 200.
router = APIRouter(
    prefix="/core",
    tags=["Core"],
    responses={**IMAGE, **RESPONSES},
    default_response_class=Response,
)
bearer = HTTPBearer(auto_error=False)  # a missing token is answered as a problem, below


class ProjectContext(BaseModel):
    """Request context containing authentication and identification information."""

    virtual_lab_id: UUID | None = None
    project_id: UUID | None = None


def caller_of(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    context: Annotated[ProjectContext, Header()],
) -> Caller:
    """The caller, from ``Authorization: Bearer …`` and the project headers.

    Every route needs a token. Its validity is entitycore's
    to decide, on the first call made with it.

    Raises:
        DomainError: ``UNAUTHENTICATED`` without a bearer token.
    """
    present = require(credentials, ErrorCode.Unauthenticated, "A bearer token is required")
    return Caller(
        token=present.credentials,
        virtual_lab_id=context.virtual_lab_id,
        project_id=context.project_id,
    )


def previews_of(request: Request) -> Previews:
    """The process's preview use cases (made in the app lifespan)."""
    return request.app.state.previews


CallerDep = Annotated[Caller, Depends(caller_of)]
PreviewsDep = Annotated[Previews, Depends(previews_of)]
Dpi = Annotated[int | None, Query(ge=10, le=600)]
Format = Annotated[ImageFormat, Query(alias="format")]
Side = Annotated[int | None, Query(ge=1, le=MAX_PIXELS_SIDE)]


async def answer(
    request: Request,
    previews: Previews,
    caller: Caller,
    plan: Plan,
    extra: dict[str, str] | None = None,
) -> Response:
    """The image, or a 304 when the caller's copy is current (checked before any download)."""
    headers = {"ETag": plan.etag, "Cache-Control": CACHE_CONTROL, **(extra or {})}
    if is_current(request.headers.get("if-none-match"), plan.etag):
        return Response(status_code=304, headers=headers)
    content = await previews.draw(caller, plan)
    return Response(content, media_type=plan.media_type, headers=headers)


async def _asset_preview(
    request: Request,
    previews: Previews,
    caller: Caller,
    route: EntityRoute,
    entity_id: UUID,
    asset_id: UUID,
    spec: RenderSpec,
) -> Response:
    plan = await previews.plan(caller, route, entity_id, asset_id, spec)
    return await answer(request, previews, caller, plan)


@router.get("/cell-morphology/preview", response_model=None)
async def get_morphology_preview(
    request: Request,
    previews: PreviewsDep,
    caller: CallerDep,
    entity_id: UUID,
    asset_id: UUID,
    dpi: Dpi = None,
    image_format: Format = ImageFormat.PNG,
) -> Response:
    """Generate a preview of a morphology (SWC asset)."""
    spec = RenderSpec(dpi=dpi, image_format=image_format)
    route = EntityRoute.CellMorphology
    return await _asset_preview(request, previews, caller, route, entity_id, asset_id, spec)


@router.get("/electrical-cell-recording/preview", response_model=None)
async def get_ephys_preview(
    request: Request,
    previews: PreviewsDep,
    caller: CallerDep,
    entity_id: UUID,
    asset_id: UUID,
    dpi: Dpi = None,
    image_format: Format = ImageFormat.PNG,
) -> Response:
    """Generate a preview of an ephys trace (NWB asset)."""
    spec = RenderSpec(dpi=dpi, image_format=image_format)
    route = EntityRoute.ElectricalCellRecording
    return await _asset_preview(request, previews, caller, route, entity_id, asset_id, spec)


@router.get("/ion-channel-recording/preview", response_model=None)
async def get_ion_channel_recording_preview(
    request: Request,
    previews: PreviewsDep,
    caller: CallerDep,
    entity_id: UUID,
    asset_id: UUID,
    dpi: Dpi = None,
    image_format: Format = ImageFormat.PNG,
) -> Response:
    """Generate a preview of an ion channel recording (NWB asset)."""
    spec = RenderSpec(dpi=dpi, image_format=image_format)
    route = EntityRoute.IonChannelRecording
    return await _asset_preview(request, previews, caller, route, entity_id, asset_id, spec)


@router.get("/model-trace/preview", response_model=None)
async def get_model_trace_preview(
    request: Request, previews: PreviewsDep, caller: CallerDep, entity_id: UUID
) -> Response:
    """The stored trace thumbnail of an e-model or me-model (its ``thumbnail`` validation)."""
    plan = await previews.plan_model_trace(caller, entity_id)
    # X-Accel-Expires: nginx's lifetime for this answer (nginx hides it from the client).
    expires = {"X-Accel-Expires": str(MODEL_TRACE_NGINX_SECONDS)}
    return await answer(request, previews, caller, plan, expires)


# Last: its first path segment is a variable, so it would match the fixed paths above.
@router.get("/{simulation_type}/preview", response_model=None)
async def get_simulation_plot(  # noqa: PLR0913 - one argument per query parameter
    request: Request,
    previews: PreviewsDep,
    caller: CallerDep,
    simulation_type: Literal["single-neuron-simulation", "single-neuron-synaptome-simulation"],
    entity_id: UUID,
    asset_id: UUID,
    target: PlotTarget,
    w: Side = None,
    h: Side = None,
    image_format: Format = ImageFormat.PNG,
) -> Response:
    """Generate a preview of a simulation: its stimulus or its first recording."""
    spec = RenderSpec(image_format=image_format, target=target, width=w, height=h)
    route = EntityRoute(simulation_type)
    return await _asset_preview(request, previews, caller, route, entity_id, asset_id, spec)
