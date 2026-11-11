"""A preview: the caller, the asset, and how to draw it.

The ETag (:meth:`RenderSpec.key`) comes from the file's digest and the drawing parameters, never
the caller: a changed file is a new key, so a cached image is never stale.
"""

import hashlib
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.types import Value

RENDER_VERSION = "1"
"""Bump when a renderer draws differently: every cached image and browser ETag is then stale."""


class ImageFormat(StrEnum):
    """Supported output formats for generated thumbnails."""

    PNG = "png"
    WEBP = "webp"

    @property
    def media_type(self) -> str:
        """The HTTP media type.

        Examples:
            >>> ImageFormat.WEBP.media_type
            'image/webp'
        """
        return f"image/{self.value}"


type PlotTarget = Literal["stimulus", "simulation"]


class EntityRoute(StrEnum):
    """The entitycore route of each entity type this service draws (``/{route}/{id}/assets``)."""

    CellMorphology = "cell-morphology"
    ElectricalCellRecording = "electrical-cell-recording"
    IonChannelRecording = "ion-channel-recording"
    SingleNeuronSimulation = "single-neuron-simulation"
    SingleNeuronSynaptomeSimulation = "single-neuron-synaptome-simulation"
    ValidationResult = "validation-result"  # model traces: a stored PNG, not drawn here


class Caller(Value):
    """The caller's token and project headers, passed on to entitycore (it decides access)."""

    token: str = Field(repr=False)
    virtual_lab_id: UUID | None = None
    project_id: UUID | None = None


class Asset(Value):
    """The entitycore asset fields this service reads (``AssetRead``)."""

    id: UUID
    content_type: str
    size: int
    sha256_digest: str | None = None


class RenderSpec(Value):
    """Every parameter that changes the drawn image."""

    dpi: int | None = None
    image_format: ImageFormat = ImageFormat.PNG
    target: PlotTarget | None = None
    width: int | None = None
    height: int | None = None

    def key(self, route: EntityRoute, asset: Asset) -> str:
        """The content key of this drawing of ``asset``: 32 hex characters.

        From the file's sha256, or its id when there is none (assets do not change in place).

        Examples:
            >>> a = Asset(id=UUID(int=1), content_type="x", size=1, sha256_digest="ab")
            >>> RenderSpec(dpi=100).key(EntityRoute.CellMorphology, a)
            'cfeccccee652d87988c79e1b87d05780'
            >>> RenderSpec(dpi=100).key(EntityRoute.CellMorphology, a) != RenderSpec().key(
            ...     EntityRoute.CellMorphology, a
            ... )
            True
        """
        parts = (
            RENDER_VERSION,
            route.value,
            asset.sha256_digest or str(asset.id),
            str(self.dpi),
            self.image_format.value,
            str(self.target),
            str(self.width),
            str(self.height),
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
