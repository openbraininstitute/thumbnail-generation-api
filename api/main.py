"""
Thumbnail Generation API

This module defines a FastAPI application for a Thumbnail Generation API.
"""

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from api.core.api import ApiError
from api.router import generate, health, swc
from api.router.core import core_router
from api.settings import settings

tags_metadata = [
    {
        "name": "Health",
        "description": "Endpoints related to checking the health of the application",
    },
    {
        "name": "Generate",
        "description": "Endpoints related to generating the thumbnail of a resource",
    },
    {
        "name": "Soma",
        "description": "Endpoints related to generating the soma reconstruction of a morphology",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events set the events that will be executed at the startup (before yield)
    and the shutdown (after yield) of the application
    """
    # pylint: disable=unused-argument
    # pylint: disable=redefined-outer-name
    # Startup code
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            profiles_sample_rate=settings.sentry_profiles_sample_rate,
            environment=settings.environment,
        )
    yield


app = FastAPI(
    title="Thumbnail Generation API",
    debug=settings.debug_mode,
    lifespan=lifespan,
    version="0.6.2",
    openapi_tags=tags_metadata,
    docs_url=f"{settings.base_path}/docs",
    openapi_url=f"{settings.base_path}/openapi.json",
)


base_router = APIRouter(prefix=settings.base_path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.whitelisted_cors_urls or [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def my_custom_exception_handler(request: Request, exc: ApiError):
    print("–– – main.py:81 – exc:", exc)
    return JSONResponse(
        status_code=ApiError.http_status_code,
        content={
            "message": exc.message,
            "code": exc.error_code,
        },
    )


# ASGI middleware to capture incoming HTTP request
app.add_middleware(SentryAsgiMiddleware)

# Include routers
base_router.include_router(core_router, tags=["Core"])
base_router.include_router(generate.router, prefix="/generate", tags=["Generate"])
base_router.include_router(swc.router, prefix="/soma", tags=["Soma"])
base_router.include_router(health.router, tags=["Health"])

app.include_router(base_router)
