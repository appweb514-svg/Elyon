PYTHON := python3
PWD := $(shell pwd)

.DEFAULT_GOAL := help

.PHONY: help lint lint-python lint-web test test-python test-web dev

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: lint-python lint-web ## Lint Python et Web

lint-python: ## Lint Python (ruff + mypy)
	ruff check apps/api && ruff check player/agent && ruff check player/playback
	mypy apps/api/elyon_api --config-file apps/api/pyproject.toml
	mypy player/agent/elyon_agent --config-file player/agent/pyproject.toml
	mypy player/playback/elyon_playback --config-file player/playback/pyproject.toml

lint-web: ## Lint Web (eslint)
	pnpm --filter @elyon/web exec eslint .

test: test-python test-web ## Tests Python et Web

test-python: ## Tests Python (pytest : api + agent + playback)
	pytest apps/api
	pytest player/agent --rootdir=player/agent
	pytest player/playback --rootdir=player/playback

test-web: ## Tests Web (vitest)
	pnpm --filter @elyon/web exec vitest run

dev: ## Démarre l'environnement local avec Docker Compose
	docker compose up -d
