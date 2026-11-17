# syntax=docker/dockerfile:1.9
# nginx (port 80, image cache) in front of granian (the app), both run by supervisord.
ARG PYTHON_IMAGE=python:3.14-slim-trixie

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first: rebuilt only when the lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
# The project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE}
# libexpat1: needed by kaleido's Chromium, missing from the slim base.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx supervisor libexpat1 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/cache/nginx  # the cache; a writable volume in ECS
COPY nginx/ /etc/nginx/
COPY supervisord.conf /etc/supervisor/supervisord.conf
WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    MALLOC_ARENA_MAX=2 \
    MALLOC_MMAP_THRESHOLD_=1048576 \
    MALLOC_TRIM_THRESHOLD_=1048576 \
    LOG_FORMAT=JSON
COPY entrypoint.sh /entrypoint.sh
# MALLOC_*: give freed memory back to the system (glibc kept it after a burst, measured).
# Fail the build, not the deploy, on an import error or a broken nginx config. /tmp ships empty.
RUN MPLCONFIGDIR=/var/tmp/build-check python -c "import app.api.app" \
 && python -m app.api.nginx_cors > /tmp/nginx_cors.conf && nginx -t \
 && rm -r /var/tmp/build-check /tmp/nginx_cors.conf /tmp/nginx.pid
# The ECS task and its load balancer use port 80.
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1{os.environ.get('BASE_PATH', '')}/health\", timeout=2)"]
CMD ["/entrypoint.sh"]
