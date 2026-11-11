# syntax=docker/dockerfile:1.9
# supervisord runs two processes (supervisord.conf): nginx on port 80, the image cache, in front of
# granian on 127.0.0.1:8080, the app (workspace-manager's runner, replacing gunicorn).
ARG PYTHON_IMAGE=python:3.14-slim-trixie

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first: this layer is rebuilt only when the lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
# The project itself, installed (not editable) into the venv, bytecode compiled.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE}
# nginx and supervisor as in the old image. libexpat1: kaleido's bundled Chromium links it and the
# slim base does not ship it (found by tests/image/smoke.py: "libexpat.so.1: cannot open shared object").
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx supervisor libexpat1 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/cache/nginx  # the cache; ECS mounts a writable volume over it
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
# MALLOC_*: glibc kept freed memory after a burst (the container stayed at 1.97 of 2 GiB, measured):
# blocks over 1 MiB (files, arrays) are mmap'ed and given back when freed, the heap is trimmed above
# 1 MiB free, and 2 arenas stop each render thread from keeping its own.
# Fail the build, not the deploy, on an import error or a broken nginx config. The check writes to a
# throwaway folder, so /tmp ships empty (entrypoint.sh fills it at start, for the right owner).
RUN MPLCONFIGDIR=/var/tmp/build-check python -c "import app.api.app" \
 && python -m app.api.nginx_cors > /tmp/nginx_cors.conf && nginx -t \
 && rm -r /var/tmp/build-check /tmp/nginx_cors.conf /tmp/nginx.pid
# Port 80, as the old image: the ECS task maps containerPort 80 and its target group checks it
# (infra thumbnail-generation-api/container.tf). The nginx master runs as root to bind it; its
# workers run as www-data (nginx.conf).
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1{os.environ.get('BASE_PATH', '')}/health\", timeout=2)"]
CMD ["/entrypoint.sh"]
