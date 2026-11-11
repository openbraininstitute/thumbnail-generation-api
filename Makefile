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

test:  ## Tests, doctests and coverage
	uv run pytest --cov

check: lint typecheck test  ## Everything CI checks

openapi:  ## Regenerate openapi.json
	uv run python -m app.api.openapi

audit:  ## Known vulnerabilities in the locked dependencies
	uv run pip-audit

dev:  ## Run the app with reload, no nginx (.env)
	uv run $(ENV_FLAG) granian --interface asgi --factory --reload --port $(API_PORT) \
		app.api.app:create_app

build:  ## Build the image
	docker build -t $(IMAGE) .

smoke: build  ## Golden images drawn inside the image
	docker run --rm --read-only --tmpfs /tmp -v "$(CURDIR)/tests/fixtures:/fixtures:ro" \
		-v "$(CURDIR)/tests/image:/checks:ro" $(IMAGE) python /checks/smoke.py /fixtures

e2e: build  ## The image against a fake entitycore (cache, CORS)
	python3 tests/image/e2e_nginx.py $(IMAGE)

old-image:  ## Build the old service's image (OLD_COMMIT)
	git archive $(OLD_COMMIT) | docker build -q -t $(OLD_IMAGE) -

parity: build  ## [local scripts/] Old vs new: same answers and pixels
	@docker image inspect $(OLD_IMAGE) >/dev/null 2>&1 || $(MAKE) --no-print-directory old-image
	uv run python scripts/parity.py $(OLD_IMAGE) $(IMAGE)

bench: build  ## [local scripts/] Old vs new: latency and memory
	@docker image inspect $(OLD_IMAGE) >/dev/null 2>&1 || $(MAKE) --no-print-directory old-image
	cd scripts && uv run python bench.py $(OLD_IMAGE) $(IMAGE)

stress-test-old: old-image  ## [local scripts/] Stress test the old image against staging
	uv run python scripts/stress.py run old $(OLD_IMAGE)

stress-test-new: build  ## [local scripts/] Stress test the new image against staging
	uv run python scripts/stress.py run new $(IMAGE)

stress-report:  ## [local scripts/] Old and new stress results side by side
	uv run python scripts/stress.py report

up:  ## Run the image and the cache dashboard
	docker compose up -d --build --wait
	@echo "api             http://localhost:$(API_PORT)/docs"
	@echo "cache dashboard http://localhost:$(CACHE_UI_PORT)"

watch:  ## Run the stack, rebuild on every change
	docker compose up --build --watch

open-api:  ## Open the API docs (after make up)
	$(OPEN) http://localhost:$(API_PORT)/docs

open-cache:  ## Open the cache dashboard (after make up)
	$(OPEN) http://localhost:$(CACHE_UI_PORT)

down:  ## Stop it all
	docker compose down --remove-orphans

reset:  ## Remove the local stack and its data, then up
	@# Images are kept, so the rebuild is fast.
	docker compose down --volumes --remove-orphans
	@$(MAKE) --no-print-directory up

logs:  ## Follow nginx and app logs
	docker compose logs -f api

cache-ls:  ## List nginx's cached images
	@docker compose exec api sh -c 'grep -rah "^KEY: " /var/cache/nginx | cut -c6- | sort; \
		echo "--"; echo "$$(grep -rl "^KEY: " /var/cache/nginx | wc -l) entries, $$(du -sh /var/cache/nginx | cut -f1)"'

dashboard-clear:  ## Empty the dashboard's data (keeps the cache)
	docker compose exec api sh -c ': > /var/log/nginx-local/access.log'
	docker compose restart goaccess

cache-clear:  ## Empty nginx's cache (restarts the api)
	docker compose restart api
