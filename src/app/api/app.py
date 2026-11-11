"""ASGI app factory, served by ``granian --factory app.api.app:create_app``.

Routes include ``BASE_PATH`` in their path: operation ids come from it, and neuroagent-ts names its
generated types after them.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio.to_thread
import httpx2
import sentry_sdk
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import problems, routes
from app.api.request_log import RequestLog
from app.application.admission import Admission
from app.application.ports import EntityCore
from app.application.previews import Previews
from app.infrastructure.entitycore import HttpEntityCore
from app.logs import configure_from, get_logger, package_version
from app.rendering import warm_up
from app.settings import Settings, get_settings

log = get_logger("api")

TAGS = [
    {"name": "Core", "description": "Previews of entitycore assets"},
    {
        "name": "Health",
        "description": "Endpoints related to checking the health of the application",
    },
]


def create_app(settings: Settings | None = None, entitycore: EntityCore | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Settings to use; read from the environment when omitted.
        entitycore: The entitycore port; the HTTP adapter when omitted (tests pass a fake).

    Returns:
        The FastAPI app.
    """
    settings = settings or get_settings()
    configure_from(settings, component="api")
    if settings.sentry.dsn:  # before the app exists, so the FastAPI integration wraps it
        sentry_sdk.init(
            dsn=settings.sentry.dsn,
            traces_sample_rate=settings.sentry.traces_sample_rate,
            profiles_sample_rate=settings.sentry.profiles_sample_rate,
            environment=settings.environment.value,
        )
    base = settings.api.base_path

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # One pooled client per process; the cap makes a burst queue here, not at entitycore.
        connections = settings.entitycore.max_connections
        http = httpx2.AsyncClient(
            timeout=settings.entitycore.timeout_seconds,
            limits=httpx2.Limits(
                max_connections=connections, max_keepalive_connections=connections
            ),
        )
        port = entitycore or HttpEntityCore(
            http,
            base_url=settings.entitycore.uri,
            max_asset_bytes=settings.max_asset_bytes,
            download_seconds=settings.entitycore.download_seconds,
        )
        admission = Admission(
            memory_bytes=settings.render.memory_bytes, downloads=settings.render.downloads
        )
        app.state.previews = Previews(
            port, concurrency=settings.render.concurrency, admission=admission
        )
        await anyio.to_thread.run_sync(warm_up)
        log.info("started", version=package_version(), base_path=base)
        try:
            yield
        finally:
            await http.aclose()

    app = FastAPI(
        title="Thumbnail Generation API",
        version=package_version(),
        lifespan=lifespan,
        openapi_tags=TAGS,
        docs_url=f"{base}/docs",
        openapi_url=f"{base}/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    problems.install(app)
    app.add_middleware(RequestLog)
    # Outermost, so a preflight never reaches the routes. Bearer tokens only: no credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_origin_regex=settings.api.cors_origin_regex.pattern
        if settings.api.cors_origin_regex
        else None,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag"],
        max_age=600,
    )
    app.include_router(routes.router, prefix=base)

    @app.get(f"{base}/health", tags=["Health"])
    async def health(response: Response) -> dict[str, str]:
        """Liveness for the load balancer and the container. No I/O."""
        response.headers["Cache-Control"] = "no-cache"
        return {"status": "OK"}

    return app
