SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

API_PORT ?= 8003
CACHE_UI_PORT ?= 7890
IMAGE ?= thumbnail-generation-api:local
OLD_IMAGE ?= thumbnail-generation-api:old
OLD_COMMIT ?= 5fd0a51  # the last commit before the re-architecture
ENV_FLAG := $(if $(wildcard .env),--env-file .env)
OPEN := $(if $(filter Darwin,$(shell uname -s)),open,xdg-open)  # the default browser
export IMAGE API_PORT CACHE_UI_PORT

.PHONY: help install lint format typecheck test check openapi audit dev build smoke e2e up down \
	logs cache-ls cache-clear open-api open-cache old-image parity bench stress-test-old \
	stress-test-new stress-report watch dashboard-clear reset

help:  ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create .venv from uv.lock
	uv sync --locked

lint:  ## ruff check and format check
	uv run ruff check .
	uv run ruff format --check .

format:  ## ruff format and fix
	uv run ruff format .
	uv run ruff check --fix .

typecheck:  ## ty check
	uv run ty check

test:  ## Tests, doctests and coverage (golden images, openapi.json, .env.example checks)
	uv run pytest --cov

check: lint typecheck test  ## Everything CI checks

openapi:  ## Regenerate openapi.json (neuroagent-ts generates its types from it)
	uv run python -m app.api.openapi

audit:  ## Known vulnerabilities in the locked dependencies
	uv run pip-audit

dev:  ## Run the api on this machine with reload, no nginx (settings from .env when it exists)
	uv run $(ENV_FLAG) granian --interface asgi --factory --reload --port $(API_PORT) \
		app.api.app:create_app

build:  ## Build the image
	docker build -t $(IMAGE) .

smoke: build  ## Draw every golden case inside the image (read-only root) and compare pixels
	docker run --rm --read-only --tmpfs /tmp -v "$(CURDIR)/tests/fixtures:/fixtures:ro" \
		-v "$(CURDIR)/scripts:/scripts:ro" $(IMAGE) python /scripts/smoke.py /fixtures

e2e: build  ## The image against a fake entitycore: nginx cache, CORS, cache lock
	python3 scripts/e2e_nginx.py $(IMAGE)

old-image:  ## Build the old service's image from git (OLD_COMMIT), for parity and bench
	git archive $(OLD_COMMIT) | docker build -q -t $(OLD_IMAGE) -

parity: build  ## Old vs new image: every thumbnail route, same status, type and pixels
	@docker image inspect $(OLD_IMAGE) >/dev/null 2>&1 || $(MAKE) --no-print-directory old-image
	uv run python scripts/parity.py $(OLD_IMAGE) $(IMAGE)

bench: build  ## Old vs new image: miss and hit latency, bursts, memory
	@docker image inspect $(OLD_IMAGE) >/dev/null 2>&1 || $(MAKE) --no-print-directory old-image
	cd scripts && uv run python bench.py $(OLD_IMAGE) $(IMAGE)

stress-test-old: old-image  ## Stress test the OLD image against staging (resources of the ECS task)
	uv run python scripts/stress.py run old $(OLD_IMAGE)

stress-test-new: build  ## Stress test the NEW image against staging (resources of the ECS task)
	uv run python scripts/stress.py run new $(IMAGE)

stress-report:  ## Old and new stress results side by side (reports/stress-*.json)
	uv run python scripts/stress.py report

up:  ## Run the image (nginx + app) and the cache dashboard with compose
	docker compose up -d --build --wait
	@echo "api             http://localhost:$(API_PORT)/docs"
	@echo "cache dashboard http://localhost:$(CACHE_UI_PORT)"

watch:  ## Run the stack and rebuild the api on every change in src/, nginx/, .env... (Ctrl-C stops)
	docker compose up --build --watch

open-api:  ## Open the API docs (through nginx) in the browser; run `make up` first
	$(OPEN) http://localhost:$(API_PORT)/docs

open-cache:  ## Open the cache dashboard (GoAccess) in the browser; run `make up` first
	$(OPEN) http://localhost:$(CACHE_UI_PORT)

down:  ## Stop it all
	docker compose down --remove-orphans

reset:  ## Start the local stack from zero: containers, nginx's cache, the dashboard's data; then `up`
	@# The cache is a tmpfs, so it goes with the container; --volumes removes the access log and
	@# the report. Images are kept (their layer cache makes the rebuild in `up` fast).
	docker compose down --volumes --remove-orphans
	@$(MAKE) --no-print-directory up

logs:  ## Follow the api container's logs (nginx and app)
	docker compose logs -f api

cache-ls:  ## What nginx's cache holds now: one key (image parameters) per line, then the total
	@docker compose exec api sh -c 'grep -rah "^KEY: " /var/cache/nginx | cut -c6- | sort; \
		echo "--"; echo "$$(grep -rl "^KEY: " /var/cache/nginx | wc -l) entries, $$(du -sh /var/cache/nginx | cut -f1)"'

dashboard-clear:  ## Empty the cache dashboard's data (nginx's access log) and restart it; the cache is kept
	docker compose exec api sh -c ': > /var/log/nginx-local/access.log'
	docker compose restart goaccess

cache-clear:  ## Empty nginx's cache in the local stack (restarts the api container)
	docker compose restart api
