.PHONY: help install dev test lint format check seed serve eval docker clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package
	python -m pip install -e .

dev: ## Install with development dependencies
	python -m pip install -e ".[dev]"

test: ## Run the full test suite with coverage
	python -m pytest --cov=agentforge --cov-report=term-missing --cov-report=xml --cov-fail-under=85

lint: ## Run static analysis
	ruff check . && ruff format --check .

format: ## Auto-format code
	ruff check --fix . && ruff format .

check: lint test ## Lint and test

seed: ## Seed the synthetic knowledge base
	agentforge seed

serve: ## Run the API with auto-reload
	agentforge serve --reload

eval: ## Run the golden evaluation set
	agentforge eval --fail-under 1.0

docker: ## Build and run the container
	docker compose up --build

clean: ## Remove runtime and test artifacts
	rm -rf var .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
