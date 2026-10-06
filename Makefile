# Developer tasks. Requires: uv, pnpm (Node 22+). Run `make help`.
.DEFAULT_GOAL := help
BACKEND := backend
FRONTEND := frontend
# Override when the uv-installed ruff binary cannot run (e.g. NixOS): make lint RUFF=ruff
RUFF ?= uv run ruff
DATA_DIR ?= $(CURDIR)/.dev-data

.PHONY: help install dev dev-backend dev-frontend check test lint format typecheck i18n conformance golden-update gen-api build serve docker

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && pnpm install --frozen-lockfile

dev: ## Run backend (:8765) and Vite (:5173) together
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && FRAME_IT_DATA_DIR=$(DATA_DIR) uv run frame-it serve --reload

dev-frontend:
	cd $(FRONTEND) && pnpm dev

check: lint typecheck i18n conformance test ## Everything that must pass before committing

test: ## Backend unit + API tests
	cd $(BACKEND) && uv run pytest

lint: ## Ruff + ESLint
	cd $(BACKEND) && $(RUFF) check src tests && $(RUFF) format --check src tests
	cd $(FRONTEND) && pnpm lint

format: ## Auto-format backend and frontend
	cd $(BACKEND) && $(RUFF) format src tests && $(RUFF) check --fix src tests
	cd $(FRONTEND) && pnpm format

typecheck: ## mypy (strict) + tsc
	cd $(BACKEND) && uv run mypy src tests
	cd $(FRONTEND) && pnpm typecheck

i18n: ## Verify i18n keys
	cd $(FRONTEND) && pnpm i18n:check

conformance: ## TypeScript geometry vs shared fixtures (Python side runs in pytest)
	cd $(FRONTEND) && pnpm conformance

golden-update: ## Regenerate golden reference renders (review the diff before committing!)
	cd $(BACKEND) && GOLDEN_UPDATE=1 uv run pytest tests/golden

gen-api: ## Regenerate frontend API types and docs/schemas/ (JSON Schemas) from the backend
	cd $(BACKEND) && uv run frame-it openapi -o ../$(FRONTEND)/src/api/openapi.json
	cd $(BACKEND) && uv run frame-it schemas -o ../docs/schemas
	cd $(FRONTEND) && pnpm gen-api

build: ## Build the frontend into the backend package (static/)
	cd $(FRONTEND) && pnpm build

serve: build ## Build then serve the full app on :8765
	cd $(BACKEND) && FRAME_IT_DATA_DIR=$(DATA_DIR) uv run frame-it serve

docker: ## Build the Docker image
	docker build -f docker/Dockerfile -t frame-it:dev .
