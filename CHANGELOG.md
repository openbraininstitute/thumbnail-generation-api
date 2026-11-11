# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 10/11/2026

Re-architecture. Same URLs, parameters, operation ids and images.

### Security

- The simulation route requires a bearer token (it forwarded anonymous requests).
- A request without a bearer token never reads the nginx cache (the app answers 401). The old cache
  served a stored image to a request with no token at all.
- Removed the Nexus routes that fetched any caller-given URL with the caller's token.
- Responses are `Cache-Control: private, max-age=3600` with an `ETag`: shared proxies never store
  an image. Presigned download URLs are no longer logged.
- Asset size limit (`ENTITY_CORE_MAX_ASSET_BYTES`) and bounds on simulation `w` and `h` (1 to 4096).
- The app runs as www-data, not root. NWB datasets over 256 MiB once decoded are refused before
  reading (a small compressed file could fill the memory). CORS values that could change nginx's
  config stop the start. `X-Content-Type-Options: nosniff` everywhere.
- Not changed yet (planned next): a cached image is sent to any request with a bearer token,
  without checking that the caller may read the entity.

### Fixed

- Errors return their real status (401, 403, 404, 409, 422, 503, 500). Every `ApiError` was 400.
- entitycore 401 and 403 are passed on instead of becoming 404 or 500.
- An ion channel recording with one trace no longer fails (division by zero).

### Changed

- Errors are RFC 9457 problems (`application/problem+json`) with a stable `code`; the kept codes
  (`ASSET_NOT_FOUND`, `CONTENT_EMPTY`, `VALIDATION_RESULT_NOT_FOUND`) keep their value.
- nginx cache key: only the parameters that change the image, in a fixed order (query order and
  unknown parameters no longer split the cache). Only images are stored: the old config stored a
  404 for a minute, so one refused caller hid the image from everyone. The stored image holds no
  CORS header; nginx adds it per request from the app's allow-list (the old cache sent the first
  caller's origin to everyone). `proxy_cache_lock` draws once for concurrent misses; keep-alive
  connections to the app. nginx logs are JSON with the app's `request_id`.
- granian replaces gunicorn under supervisord. Port 80 and `{BASE_PATH}/health` are unchanged.
- Each log line is one write: lines of nginx and the two app workers no longer merge.
- One pooled HTTP client per process for entitycore and storage (was one per request).
- Admission control per process: a memory budget (3x each file's size, `RENDER_MEMORY_BYTES`) and a
  download cap (`RENDER_DOWNLOADS`); a connection cap to entitycore (`ENTITY_CORE_MAX_CONNECTIONS`);
  glibc settings that give freed memory back. The staging stress test (make stress-test-old / stress-test-new)
  had killed the container for memory, old and new, before these.
- Ion channel thumbnails render up to 7x faster on long recordings (artifact smoothing vectorised,
  same pixels). matplotlib pinned to 3.10: 3.11 would move the ephys tick labels.
- Python 3.14, `src/app` package and tooling as workspace-manager (uv, ruff ALL, ty, structlog JSON logs).
- CORS no longer allows credentials (bearer tokens, no cookies).

### Added

- `Server-Timing` on every response: queue, entitycore metadata, download, render, total; a
  cache hit says `HIT`. Readable by allowed origins (`Timing-Allow-Origin`).
- `make parity`: the old and new images answer the same requests; every thumbnail must be the
  same image. `make bench`: latency, bursts and memory of both. `make open-api`, `make open-cache`.
- Local cache dashboard (`make up`): GoAccess on http://localhost:7890 shows each request's cache
  status (HIT, MISS, BYPASS) and the most asked images; `make cache-ls` lists the stored entries.
- `.env.example`: every setting, its default and a plain explanation; a test keeps it in step with
  `settings.py`.

### Removed

- `/generate/morphology-image`, `/generate/trace-image`, `/generate/simulation-plot` and
  `/soma/process-nexus-swc`: no caller in core-web-app or neuroagent-ts; the soma route needed a
  Blender binary the image never shipped.

## [0.6.2] - 13/09/2024

### Fixed

- Add clearing of figure cache to avoid memory leaks

## [0.6.1] - 13/09/2024

### Fixed

- Add case when receiving `403` error from Nexus

### Updated

- Re-organised unit test fixtures to include them in conftest file
- Make Sentry metrics environment variables

## [0.6.0] - 27/08/2024

### Fixed

- Edge case when generated soma file contains underscore not being found
- Look for response using property starting in vcs_, ccs_ or ic_, instead of just ic_
- Exception thrown when user is not authorized to access nexus resource

### Updated

- Dependency versions for `fastapi/gunicorn/requests/sentry/black`

### Added

- Endpoint for generating single neuron simulation plot images

## [0.5.3] - 08/08/2024

### Fixed

- Soma generation issue due to authorization problem
- `docker-compose` environment variables
  
### Removed

- Deprecated `POST /soma/process-swc` endpoint

## [0.5.2] - 25/07/2024

### Added

- Github actions pipeline for testing and deploying

## [0.5.1] - 21/06/2024

### Added

- Acknowledgements section in README
- Authors.txt file 

## [0.5.0] - 20/06/2024

### Added

- Sentry configuration for better exception tracking
- Files to prepare repository for open sourcing
 
### Modified

- Exception handling in API
- Move functions to `services` and `utils` modules to differentiate business logic
- Pydoc strings to make them uniform
- Add unit tests related to `services` and `utils`
- Replace `matplotlib` `set_tight_layout()` with `set_layout_engine` due to deprecation
- Replace `config` by `Settings` class for better settings organization

## [0.4.4] - 11/06/2024

### Fixed

- Documentation styles when deployed under base path

## [0.4.3] - 29/05/2024

### Added

- `BASE_PATH` environment variable to set a prefix for endpoints

## [0.4.2] - 21/05/2024

### Modified

- Remove option Y-up to keep original coordinates

## [0.4.1] - 12/05/2024

### Fixed

- Fix pipeline pushing in Dockerhub failing due to lack of memory

## [0.4.0] - 06/05/2024

### Added

- NeuroMorphoVis integration for soma reconstruction

### Modified

- Downgrade Python version to `3.10` to support dependencies

## [0.3.0] - 05/04/2024

### Removed

- Server configuration folder

### Modified

- Folder structure to include only `/api`
- Installation to use `poetry`
- Python version to `3.12`

## [0.2.3] - 12/02/2024

### Fixed

- Dockerhub image deployment path

## [0.2.2] - 07/02/2024

### Added

- CI job to deploy service in Dockerhub

## [0.2.1] - 30/01/2024

### Fixed

- Ephys plot images not closing (memory issue)

## [0.2.0] - 25/01/2024

### Added

- Endpoint for generating electrophysiology trace images
- Environment variables in docker-compose

## [0.1.1] - 16/01/2024

### Added

- Whitelisted CORS URLs as environment variables
- README.md file

## [0.1.0] - 15/01/2024

### Added

- Initialize FASTAPI application
- Add Gitlab CI pipeline to lint, test and deploy
- Add NGINX server to enable caching
- Add black and pylint linters
