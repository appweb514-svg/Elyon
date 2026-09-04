PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PWD := $(shell pwd)

.DEFAULT_GOAL := help

.PHONY: help lint lint-python lint-web test test-python test-web dev lab lab-arm lab-down lab-logs lab-local lab-hosted lab-hosted-web lab-hosted-players

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: lint-python lint-web ## Lint Python et Web

lint-python: ## Lint Python (ruff + mypy)
	.venv/bin/ruff check apps/api && .venv/bin/ruff check player/agent && .venv/bin/ruff check player/playback && .venv/bin/ruff check player/lab/bootstrap.py
	.venv/bin/mypy apps/api/elyon_api --config-file apps/api/pyproject.toml
	.venv/bin/mypy player/agent/elyon_agent --config-file player/agent/pyproject.toml
	.venv/bin/mypy player/playback/elyon_playback --config-file player/playback/pyproject.toml

lint-web: ## Lint Web (eslint)
	cd apps/web && ./node_modules/.bin/eslint src

test: test-python test-web ## Tests Python et Web

test-python: ## Tests Python (pytest : api + agent + playback)
	.venv/bin/pytest apps/api
	.venv/bin/pytest player/agent --rootdir=player/agent
	.venv/bin/pytest player/playback --rootdir=player/playback

test-web: ## Tests Web (vitest)
	cd apps/web && NODE_ENV=test ./node_modules/.bin/vitest run

dev: ## Démarre l'environnement local avec Docker Compose
	docker compose up -d

LAB_COMPOSE := docker compose -f compose.yaml -f compose.lab.yaml

lab: ## Serveur + 2 Raspberry Pi émulés (enrôlés, publiés)
	mkdir -p .lab/enroll
	$(LAB_COMPOSE) up -d --build
	$(PYTHON) player/lab/bootstrap.py --api http://127.0.0.1:8000 --enroll-dir .lab/enroll

lab-arm: ## Lab players en linux/arm64 (QEMU user-mode, Pi 4/5)
	mkdir -p .lab/enroll
	$(LAB_COMPOSE) -f compose.lab.arm64.yaml up -d --build
	$(PYTHON) player/lab/bootstrap.py --api http://127.0.0.1:8000 --enroll-dir .lab/enroll

lab-down: ## Arrête le lab et supprime volumes + codes d'enrôlement
	$(LAB_COMPOSE) down -v
	rm -rf .lab

lab-logs: ## Journaux API + players émulés
	$(LAB_COMPOSE) logs -f --tail=80 api worker player-1 player-2

lab-local: ## Lab hôte (sqlite + 2 agents + aperçu) — sans build Docker
	chmod +x player/lab/run-local.sh player/lab/bootstrap.py
	ELYON_LAB_ONCE=$${ELYON_LAB_ONCE:-0} ./player/lab/run-local.sh

lab-hosted: ## API + back-office :5140 + 3 Raspberry (exposé Tailscale)
	chmod +x player/lab/run-hosted.sh player/lab/bootstrap.py
	./player/lab/run-hosted.sh

lab-hosted-web: ## Stack web seule : API + back-office :5140 (sans players)
	chmod +x player/lab/run-web.sh
	./player/lab/run-web.sh

lab-hosted-players: ## Players émulés seuls (exige l'API en marche)
	chmod +x player/lab/run-players.sh
	./player/lab/run-players.sh

qemu-image: ## Construit l'image Raspberry Pi OS arm64 flashable (sudo requis)
	sudo $(PYTHON) -c "import os" 2>/dev/null || true
	chmod +x player/qemu/build-image.sh player/qemu/run-qemu.sh player/qemu/export-image.sh
	sudo player/qemu/build-image.sh

qemu-run: ## Boot le Raspberry Pi émulé (QEMU raspi3b, vrai système ARM64)
	player/qemu/run-qemu.sh

qemu-export: ## Extrait l'image flashable pour un vrai Raspberry Pi
	player/qemu/export-image.sh
