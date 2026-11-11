# Thumbnail Generation API

Thumbnails of [entitycore](https://github.com/openbraininstitute/entitycore) assets: cell
morphologies (SWC), electrical cell and ion channel recordings (NWB), single-neuron simulations
(JSON), and the stored trace image of e-models and me-models. Called by core-web-app and by the
neuroagent-ts AI agent.

## Routes

| Route | Asset | Query |
|-------|-------|-------|
| `GET /core/cell-morphology/preview` | SWC | `entity_id`, `asset_id`, `dpi` (10-600), `format` (`png`, `webp`) |
| `GET /core/electrical-cell-recording/preview` | NWB | same |
| `GET /core/ion-channel-recording/preview` | NWB | same |
| `GET /core/{single-neuron-simulation,single-neuron-synaptome-simulation}/preview` | JSON | `entity_id`, `asset_id`, `target` (`stimulus`, `simulation`), `w`, `h` (1-4096), `format` |
| `GET /core/model-trace/preview` | stored PNG | `entity_id` |
| `GET /health` | | |

Every route is also under `BASE_PATH` (`/api/thumbnail-generation` when deployed). Reference:
`/docs`; the document is committed as [openapi.json](openapi.json) (neuroagent-ts generates its
types from it, so operation ids and parameters must not change: `make openapi` after a route change).

### Access

Every preview request needs `Authorization: Bearer <token>`, and may send the `virtual-lab-id`
and `project-id` headers. On a cache miss the service reads the asset from entitycore with the
caller's token and headers, so entitycore refuses a caller who may not read it (404).

**Known gap (planned next, owner decision 2026-11-10):** a cached image is sent to any request with
a bearer token, without checking that the caller may read the entity. As in the old service.

### Caching

- **Server (nginx):** nginx runs in front of the app (supervisord) and keeps each image, keyed by
  the parameters that change it (`entity_id`, `asset_id`, `dpi`, `format`, `target`, `w`, `h`), in
  a fixed order. A hit makes no call to the app or entitycore. Only images are stored, never errors.
  Concurrent misses share one render (`proxy_cache_lock`). 1 GB on disk, 7 days unused.
  [nginx/nginx.conf](nginx/nginx.conf). Every preview response says `X-Cache: HIT` or `MISS`.
- **Client:** `Cache-Control: private, max-age=3600` and an `ETag`: the browser reuses the image
  for an hour, then revalidates and gets an empty 304 when it is unchanged. No shared proxy stores it.
- **CORS:** nginx adds `Access-Control-Allow-Origin` per request, from the same allow-list as the
  app (`WHITELISTED_CORS_URLS`, `CORS_ORIGIN_REGEX`), so one cached image serves every origin.

### Timing

Every response has a `Server-Timing` header (W3C standard; shown in the browser's DevTools under
Network > a request > Timing):

```
miss:  meta;dur=13.9, queue;dur=0.0, download;dur=315.0, render_wait;dur=0.2, render;dur=118.5, app;dur=456.4, cache;desc="MISS"
hit:   cache;desc="HIT"
```

`meta`: entitycore's asset details. `queue`: waiting for a download slot and memory. `download`:
the file. `render_wait`: waiting for a render slot (high when the process is busy). `render`: the
drawing alone. `app`: the whole request in the app. The request log line carries the same phases
(`meta_ms`, `render_wait_ms`, `render_ms`...).

### Errors

[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problems (`application/problem+json`):

```json
{"type": "about:blank", "title": "Asset not found", "status": 404,
 "detail": "Asset not found or not readable", "code": "ASSET_NOT_FOUND"}
```

Codes and statuses: [src/app/api/problems.py](src/app/api/problems.py).

## Run

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.14) and Docker.

```bash
make install
```

```bash
cp .env.example .env
```

[.env.example](.env.example) lists every setting with its default value and what it does. Change
values in `.env` (git ignores it).

### Locally with nginx and the cache dashboard (as in production)

```bash
make up
```

- API through nginx and its cache: http://localhost:8003/docs
- Cache dashboard ([GoAccess](https://goaccess.io), live): http://localhost:7890. Its "Cache
  Status" panel counts HIT (served from the cache), MISS (drawn, then stored) and BYPASS (not
  cacheable: health, docs, no token). "Requested Files" lists every image URL with its hits and
  times.

```bash
make cache-ls
```

`make open-api` and `make open-cache` open them in your browser.

```bash
make watch
```

`make watch` does the same as `make up`, and stays running: when you change a file in `src/`,
`nginx/`, `supervisord.conf`, `entrypoint.sh`, `pyproject.toml`, `uv.lock` or `.env`, it rebuilds
the api image (about 40 seconds: the dependencies are cached) and replaces the container, so what
you test is always the production image. For a quick edit-and-see loop on the app alone, with
reload in about a second, use `make dev`. The dashboard's own files (`nginx/dashboard/`, `nginx/local/`) are read at
start: after changing them, run `make up` again.

To start clean: `make dashboard-clear` empties the dashboard's data (it keeps cached images),
`make cache-clear` empties the image cache (it keeps the dashboard), and `make down` followed by
`docker compose down -v` removes both for good.

`make cache-ls` lists what nginx's cache holds right now, one line per image (path, entity,
asset, dpi, format, target, w, h), then the count and the size. `make cache-clear` empties it,
`make logs` follows nginx and app logs, `make down` stops everything.

### The app alone, with reload (no nginx, so no server cache)

```bash
make dev
```

The api is at http://127.0.0.1:8003/docs.

Example (a staging token in `AUTH_TOKEN`):

```bash
curl -i "http://127.0.0.1:8003/core/cell-morphology/preview?entity_id=$ENTITY_ID&asset_id=$ASSET_ID&dpi=100&format=webp" -H "Authorization: Bearer $AUTH_TOKEN" -o morphology.webp
```

## Layout

```
nginx/             nginx.conf (the image cache), includes/; the CORS list is written at start
  local/           local only: the access log the cache dashboard reads (compose.yaml)
  dashboard/       local only: serves the GoAccess dashboard
compose.yaml       api (nginx + app, as in AWS), goaccess, cache-ui
.env.example       every setting, its default and what it does
supervisord.conf   runs nginx (port 80) and granian (127.0.0.1:8080) in the container
scripts/           smoke.py (golden pixels in the image), e2e_nginx.py (cache over HTTP)
src/app/
  api/             routes, RFC 9457 problems, request log, app factory (granian runs create_app)
  application/     preview use cases (plan, draw), the entitycore port
  domain/          values (RenderSpec, Asset, Caller), error codes, guards
  rendering/       one module per asset type; RENDERERS maps an entity type to its renderer
  infrastructure/  entitycore over HTTP
  settings.py      typed settings, one group per topic
  logs.py          structlog, one JSON line per event
```

A new asset type is one module in `rendering/`, one line in `RENDERERS`, one route, and a golden
image test.

## Check

```bash
make check
```

Lint (ruff), types (ty), tests with coverage. The tests include the golden images (every renderer
must draw the pixels the old service drew), the `openapi.json` drift check, and doctests.

```bash
make smoke
```

```bash
make e2e
```

```bash
make parity
```

```bash
make bench
```

`make parity` builds the old service's image from git and sends the same requests to both images:
every thumbnail route must give the same status, type and pixels. `make bench` measures misses,
hits, bursts and memory of both.

### Stress test against staging

```bash
make stress-test-old
```

```bash
make stress-test-new
```

```bash
make stress-report
```

Each command signs in as the obi-e2e QA user (credentials from `../obi-e2e/.env.staging.local`,
or `E2E_TEST_USERNAME` / `E2E_TEST_PASSWORD`), starts the image with the staging ECS task's
resources (ARM64, 2 vCPU, 2 GiB hard memory limit, read-only root), and loads it like the web
app's grids: 50, then 100, then 200 thumbnails at the same moment for morphologies, ephys, ion
channel recordings and model traces, from an empty cache and then again from the cache. Run them
one after the other, never together: they use staging entitycore. Results: `reports/`.

`make smoke` draws every golden case inside the Docker image. `make e2e` runs the image against a
fake entitycore and checks over HTTP: no token is 401, a refused miss is not stored, a hit makes
no entitycore call, query order does not matter, 304, CORS and preflight, eight concurrent misses
download once, and the known access gap (a check that will change when access is added). CI runs
both.

## Acknowledgements

The development of this software was supported by funding to the Blue Brain Project, a research center of the École polytechnique fédérale de Lausanne (EPFL), from the Swiss government’s ETH Board of the Swiss Federal Institutes of Technology.

For license and authors, see LICENSE.txt and AUTHORS.txt respectively.

Copyright &copy; 2024 Blue Brain Project/EPFL

Copyright &copy; 2025 Open Brain Institute
