SHELL := /bin/bash

export ENVIRONMENT ?= local
export APP_NAME := thumb-api
export IMAGE_NAME ?= $(APP_NAME)

.PHONY: help install lint format test check-format lint

define load_env
	# all the variables in the included file must be prefixed with export
	$(eval ENV_FILE := .env.$(1))
	@echo "Loading env from $(ENV_FILE)"
	$(eval include $(ENV_FILE))
endef

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-23s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies into .venv
	uv sync --no-install-project

compile-deps:  ## Create or update the lock file, without upgrading the version of the dependencies
	uv lock

upgrade-deps:  ## Create or update the lock file, using the latest version of the dependencies
	uv lock --upgrade

check-deps:  ## Check that the dependencies in the existing lock file are valid
	uv lock --locked

dev:  ## Run development server
	@$(call load_env,local)
	uv run uvicorn api.main:app --reload --port 8003

format: ## Format code using ruff
	uv run ruff format .

check-format: ## Check code formatting without making changes
	uv run ruff format --check .

lint-fix:
	uv run ruff check --fix .

lint:
	uv run ruff check .

lint-all: check-format lint typecheck ## Run all linting checks

typecheck:
	uv run pyright api

test: ## Run tests
	uv run pytest

ci: format lint test ## Run all CI checks (linting and tests)

build:
	docker build --platform linux/amd64 -t thumbnail-api .

up:  ## Run the application in Docker with docker compose
	mkdir -p output
	docker compose --progress=plain build thumbnail-api
	docker compose -f docker-compose.yaml up --remove-orphans

destroy:  ## Take down the application and remove the volumes
	docker compose down --remove-orphans --volumes
