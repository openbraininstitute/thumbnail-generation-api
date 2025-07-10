# syntax=docker/dockerfile:1.9
ARG UV_VERSION=latest
ARG PYTHON_VERSION=3.12
ARG PYTHON_BASE=${PYTHON_VERSION}

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:$PYTHON_BASE

ENV \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PYTHON=python${PYTHON_VERSION} \
  PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  vim \
  supervisor \
  nginx \
  jq \
  htop \
  strace \
  net-tools \
  iproute2 \
  psmisc \
  procps \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
  uv --version && uv sync --locked --no-install-project --no-dev

COPY ./nginx/ /etc/nginx/
COPY ./supervisord.conf /etc/supervisor/supervisord.conf
COPY api/ /app/api/

EXPOSE 80

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
