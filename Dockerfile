# syntax=docker/dockerfile:1.9
ARG UV_VERSION=latest
ARG PYTHON_VERSION=3.12
ARG PYTHON_BASE=${PYTHON_VERSION}

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:$PYTHON_BASE

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PYTHON=python${PYTHON_VERSION} \
  PATH="/app/.venv/bin:/app/blender/bbp-blender-3.5/blender-bbp:${PATH}"

RUN apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  wget \
  unzip \
  curl \
  libxi6 \
  libgl1 \
  libsm6 \
  xz-utils \
  libxfixes3 \
  libxrender1 \
  libdbus-1-3 \
  libxkbcommon0 \
  git \
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
  libxml2-dev \
  libxslt1-dev \
  python3-libxml2 \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app


RUN wget https://raw.githubusercontent.com/BlueBrain/NeuroMorphoVis/master/setup.py  \
  && chmod +x setup.py \
  && mkdir blender \
  && mkdir output \
  && chmod 777 blender

RUN python ./setup.py --prefix=./blender --verbose

# Clone the specific branch of NeuroMorphoVis repo to temp directory,
# copy neuromorphovis.py to /app and make it executable
# move files to /app
# and clean up
RUN git clone --depth 1 https://github.com/BlueBrain/NeuroMorphoVis.git /temp/NeuroMorphoVis \
  && cp -r /temp/NeuroMorphoVis/nmv /app/ \
  && cp /temp/NeuroMorphoVis/neuromorphovis.py /app/ \
  && chmod +x neuromorphovis.py \
  && rm -rf /temp/NeuroMorphoVis \
  && apt-get remove -y git && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

#PATCH https://github.com/BlueBrain/NeuroMorphoVis.git
COPY ./nmv/options/neuromorphovis_options.py /app/nmv/options/
#soma_reconstruction.py has export to glb patched in
COPY ./nmv/interface/cli/soma_reconstruction.py /app/interface/cli/

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
