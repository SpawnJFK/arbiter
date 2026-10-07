# Arbiter developer commands. Run from the repo root.
# Python commands run inside services/api with its virtualenv (.venv) if present.

SHELL := /bin/bash
API_DIR := services/api
WEB_DIR := apps/web
DEV_COMPOSE := docker compose -f deploy/docker-compose.dev.yml
PY := $(shell [ -x $(API_DIR)/.venv/bin/python ] && echo .venv/bin/python || echo python3)
export ARBITER_DATABASE_URL ?= postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter
export ARBITER_TEST_DATABASE_URL ?= postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter_test

.PHONY: help install dev-db dev-db-down migrate api worker web test lint fmt

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Create services/api/.venv and install API (dev extras) + web deps
	cd $(API_DIR) && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[dev]'
	cd $(WEB_DIR) && if [ -f package-lock.json ]; then npm ci; else npm install; fi

dev-db: ## Start local Postgres 16 + pgvector (dbs: arbiter, arbiter_test)
	$(DEV_COMPOSE) up -d --wait

dev-db-down: ## Stop local Postgres (data volume kept)
	$(DEV_COMPOSE) down

migrate: ## alembic upgrade head against ARBITER_DATABASE_URL
	cd $(API_DIR) && $(PY) -m alembic upgrade head

api: ## Run the API with reload on :8000
	cd $(API_DIR) && $(PY) -m uvicorn arbiter.api.app:app --reload --host 127.0.0.1 --port 8000

worker: ## Run the pipeline worker
	cd $(API_DIR) && $(PY) -m arbiter.pipeline.worker

web: ## Run the Next.js dev server on :3000
	cd $(WEB_DIR) && NEXT_PUBLIC_API_URL=$${NEXT_PUBLIC_API_URL:-http://localhost:8000} npm run dev

test: ## Run the API test suite (needs dev-db)
	cd $(API_DIR) && $(PY) -m pytest -q

lint: ## ruff check + format check (API), eslint + tsc (web)
	cd $(API_DIR) && $(PY) -m ruff check . && $(PY) -m ruff format --check .
	cd $(WEB_DIR) && npm run lint && npx tsc --noEmit

fmt: ## Auto-fix: ruff format + ruff check --fix
	cd $(API_DIR) && $(PY) -m ruff format . && $(PY) -m ruff check --fix .
