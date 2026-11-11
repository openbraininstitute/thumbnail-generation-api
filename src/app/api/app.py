"""ASGI application factory (workspace-manager pattern).

Served by ``granian --interface asgi --factory app.api.app:create_app``.

In the Docker image, supervisord runs nginx (port 80, the image cache) in front of granian
(127.0.0.1:8080): ``nginx/nginx.conf``.

Routes are mounted under ``BASE_PATH`` (the AWS load balancer forwards ``{BASE_PATH}/*``
unstripped). Unlike workspace-manager's ``BasePath`` middleware (a root path), the prefix is part
of every route path here, because FastAPI builds operation ids from the path and neuroagent-ts
names its generated types after them (``api/routes.py``).
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
        # One client per process: keep-alive connections to entitycore and storage are reused.
        # A capped pool (Backpressure): a burst queues here instead of reaching entitycore at once.
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
            max_asset_bytes=settings.entitycore.max_asset_bytes,
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
    # Outermost, so a preflight never reaches the routes. Bearer tokens, no cookies: no
    # credentials mode (the old service allowed credentials it never used).
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
        """Process is up: the AWS target group's check and the container's. No I/O."""
        response.headers["Cache-Control"] = "no-cache"
        return {"status": "OK"}

    return app
