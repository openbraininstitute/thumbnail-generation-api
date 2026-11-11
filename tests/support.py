"""Shared test helpers: fixture files, an in-memory entitycore, pixel comparison."""

import io
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import numpy as np
from fastapi import FastAPI
from PIL import Image as PILImage

from app.api.app import create_app
from app.domain.errors import DomainError, ErrorCode
from app.domain.preview import Asset, Caller, EntityRoute
from app.settings import ApiSettings, RenderSettings, Settings

DATA = Path(__file__).parent / "fixtures" / "data"
GOLDEN = Path(__file__).parent / "fixtures" / "golden"

MEMBER = "member-token"  # entitycore lets this caller read the asset
OUTSIDER = "outsider-token"  # a valid user outside the project: entitycore answers 404


def same_pixels(a: bytes, b: bytes) -> bool:
    """Whether two encoded images decode to the same RGBA pixels."""

    def pixels(data: bytes) -> np.ndarray:
        return np.asarray(PILImage.open(io.BytesIO(data)).convert("RGBA"))

    first, second = pixels(a), pixels(b)
    return first.shape == second.shape and bool((first == second).all())


class FakeEntityCore:
    """entitycore in memory: one asset per entity, readable by the tokens in ``readers``.

    Like entitycore, a caller who may not read the entity gets 404 (``ASSET_NOT_FOUND``), so a
    private entity's existence is not revealed. ``refusal`` makes every call fail with a code.
    """

    def __init__(self) -> None:
        """No assets yet."""
        self.files: dict[UUID, tuple[EntityRoute, UUID, Asset, bytes]] = {}
        self.readers: set[str] = {MEMBER}
        self.model_traces: dict[UUID, tuple[UUID, UUID]] = {}  # entity -> (result, asset)
        self.refusal: ErrorCode | None = None
        self.asset_calls = 0
        self.content_calls = 0

    def add(
        self, route: EntityRoute, content: bytes, *, content_type: str = "x/y"
    ) -> tuple[UUID, UUID]:
        """Store a file; returns ``(entity_id, asset_id)``."""
        entity_id, asset = (
            uuid4(),
            Asset(
                id=uuid4(), content_type=content_type, size=len(content), sha256_digest=uuid4().hex
            ),
        )
        self.files[asset.id] = (route, entity_id, asset, content)
        return entity_id, asset.id

    def _check(self, caller: Caller) -> None:
        if self.refusal is not None:
            raise DomainError(self.refusal, "refused")
        if caller.token not in self.readers:
            raise DomainError(ErrorCode.AssetNotFound, "Asset not found or not readable")

    async def asset(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset_id: UUID
    ) -> Asset:
        self.asset_calls += 1
        self._check(caller)
        stored = self.files.get(asset_id)
        if stored is None or stored[:2] != (route, entity_id):
            raise DomainError(ErrorCode.AssetNotFound, "Asset not found or not readable")
        return stored[2]

    async def content(
        self, caller: Caller, route: EntityRoute, entity_id: UUID, asset: Asset
    ) -> bytes:
        self.content_calls += 1
        self._check(caller)
        return self.files[asset.id][3]

    async def model_trace(self, caller: Caller, entity_id: UUID) -> tuple[UUID, Asset]:
        self.asset_calls += 1
        self._check(caller)
        if entity_id not in self.model_traces:
            raise DomainError(ErrorCode.ValidationResultNotFound, "No thumbnail validation result")
        result_id, asset_id = self.model_traces[entity_id]
        return result_id, self.files[asset_id][2]


def settings() -> Settings:
    """Test settings: no base path."""
    api = ApiSettings(base_path="", cors_origins=["http://localhost:3000"])
    return Settings(api=api, render=RenderSettings())


@asynccontextmanager
async def client(
    fake: FakeEntityCore, app_settings: Settings | None = None
) -> AsyncGenerator[httpx2.AsyncClient]:
    """An HTTP client to the app over ASGI, with its lifespan run around it."""
    app: FastAPI = create_app(app_settings or settings(), entitycore=fake)
    async with app.router.lifespan_context(app):
        # Starlette re-raises a crash after sending its 500 (for the server's log); read the 500.
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def bearer(token: str = MEMBER, **headers: str) -> dict[str, str]:
    """Request headers with a bearer token."""
    return {"Authorization": f"Bearer {token}", **headers}
