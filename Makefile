SHELL=/bin/bash -o pipefail

all: help

update-dependencies: ## Updates requirements.txt and requirements-dev.txt from pyproject.toml
	poetry export --without-hashes --without=dev --format=requirements.txt > requirements.txt
	poetry export --without-hashes --only=dev --format=requirements.txt > requirements-dev.txt

build: ## build the API image
	docker compose build app

build-dev: ## build the API image w/ dev dependencies
	docker compose build app --build-arg DEV=True

up: ## Sets up local docker environment
	docker compose up -d

down: ## Shuts down local docker instance
	docker compose down

clean: ## Cleans docker images
	docker compose down -v --remove-orphans

run: ## Runs the API locally (no docker) on port 8081
	ALLOW_PRIVATE_ADDRESSES=true poetry run flask --app run.py run --port 8081 --debug

test: ## Runs all tests
	poetry run pytest --cov-report term-missing --junitxml=pytest.xml --cov=app ./tests | tee pytest-coverage.txt

test-unit: ## Runs unit tests
	poetry run pytest --cov-report term-missing --cov=app ./tests/unit

test-integration: ## Runs integration tests
	poetry run pytest --cov-report term-missing --cov=app ./tests/integration

lint: ## Lints and formats the code
	poetry run ruff check . --fix
	poetry run black .
	poetry run isort .

lint-check: ## Checks linting without changing files
	poetry run ruff check .
	poetry run black --check .
	poetry run isort --check-only .

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: all update-dependencies build build-dev up down clean run test test-unit test-integration lint lint-check help
