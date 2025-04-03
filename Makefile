SHELL := /bin/bash

export ENVIRONMENT ?= local
export APP_NAME := thumb-api
export IMAGE_NAME ?= $(APP_NAME)

.PHONY: help install lint format test check-format lint-pylint

define load_env
	# all the variables in the included file must be prefixed with export
	$(eval ENV_FILE := .env.$(1))
	@echo "Loading env from $(ENV_FILE)"
	$(eval include $(ENV_FILE))
endef

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-23s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies using poetry
	poetry install

dev:  ## Run development server
	@$(call load_env,local)
	poetry run uvicorn api.main:app --reload --port 8003

format: ## Format code using black
	poetry run black . 
	
check-format: ## Check code formatting without making changes
	poetry run black --check .

lint: check-format lint-pylint   ## Run all linting checks

test: ## Run tests
	poetry run pytest
	
ci: format lint test ## Run all CI checks (linting and tests)
	
build:
	docker build --platform linux/amd64 -t thumbnail-api .

up:  ## Run the application in Docker
	docker compose --env-file ./.env.local -f docker-compose.yaml up --watch --remove-orphans

destroy:  ## Take down the application and remove the volumes
	docker compose down --remove-orphans --volumes
