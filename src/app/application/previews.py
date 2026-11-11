"""Preview use cases: ``plan`` reads the asset's metadata (ETag, size); ``draw`` renders it.

Both run only on an nginx cache miss. entitycore decides access.
"""

import time
from uuid import UUID

import anyio
import anyio.to_thread

from app.application.admission import Admission
from app.application.ports import EntityCore
from app.domain.preview import Asset, Caller, EntityRoute, RenderSpec
from app.domain.types import Value
from app.rendering import RENDERERS, Render
from app.timing import phase, record


def is_current(if_none_match: str | None, etag: str) -> bool:
    """Whether the caller's ``If-None-Match`` names ``etag`` (RFC 9110 §13.1.2, weak compare).

    Examples:
        >>> is_current('W/"a", "b"', '"a"'), is_current("*", '"a"'), is_current(None, '"a"')
        (True, True, False)
    """
    if not if_none_match:
        return False
    tags = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return "*" in tags or etag in tags


class Plan(Value):
    """A preview to answer: what to draw, and its content key."""

    route: EntityRoute
    entity_id: UUID
    asset: Asset
    spec: RenderSpec
    media_type: str

    @property
    def key(self) -> str:
        """The content key: the ETag without its quotes."""
        return self.spec.key(self.route, self.asset)

    @property
    def etag(self) -> str:
        """The strong ETag of the image."""
        return f'"{self.key}"'


def _timed(render: Render, content: bytes, spec: RenderSpec, queued: float) -> bytes:
    """Run ``render``, timing the wait for a slot (``render_wait``) and the drawing (``render``)."""
    record("render_wait", queued)
    with phase("render"):
        return render(content, spec)


class Previews:
    """The preview use cases over one entitycore port."""

    def __init__(self, entitycore: EntityCore, *, concurrency: int, admission: Admission) -> None:
        """``concurrency``: renders at once; ``admission``: memory and downloads in flight."""
        self._entitycore = entitycore
        self._limiter = anyio.CapacityLimiter(concurrency)
        self._admission = admission

    async def plan(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset_id: UUID, spec: RenderSpec
    ) -> Plan:
        """Read the asset's metadata (as the caller) and plan its drawing.

        Raises:
            DomainError: entitycore refused the caller, asset missing, entitycore down.
        """
        with phase("meta"):  # entitycore: the asset's metadata
            asset = await self._entitycore.asset(caller, route, entity_id, asset_id)
        return Plan(
            route=route,
            entity_id=entity_id,
            asset=asset,
            spec=spec,
            media_type=spec.image_format.media_type,
        )

    async def plan_model_trace(self, caller: Caller, entity_id: UUID) -> Plan:
        """Find the stored trace thumbnail of a model (a PNG, sent as it is).

        Raises:
            DomainError: entitycore refused the caller, no thumbnail result, entitycore down.
        """
        with phase("meta"):  # entitycore: the validation result and its assets
            result_id, asset = await self._entitycore.model_trace(caller, entity_id)
        return Plan(
            route=EntityRoute.ValidationResult,
            entity_id=result_id,
            asset=asset,
            spec=RenderSpec(),
            media_type=asset.content_type,
        )

    async def draw(self, caller: Caller, plan: Plan) -> bytes:
        """The image bytes of ``plan``: the file drawn by its renderer, or the stored PNG.

        Raises:
            DomainError: Download refused or too large, file unreadable.
        """
        async with self._admission.drawing(plan.asset.size):  # records "queue"
            with phase("download"):
                content = await self._entitycore.content(
                    caller, plan.route, plan.entity_id, plan.asset
                )
            render = RENDERERS.get(plan.route)
            if render is None:  # model traces: entitycore stores the image itself
                return content
            return await anyio.to_thread.run_sync(
                _timed, render, content, plan.spec, time.perf_counter(), limiter=self._limiter
            )
