.PHONY: help up down logs migrate test lint typecheck shell-db clean install

VENV := .venv/bin

help:
	@echo "Available commands:"
	@echo "  make up        - Start database container with Docker Compose"
	@echo "  make down      - Stop containers"
	@echo "  make logs      - Tail container logs"
	@echo "  make migrate   - Run Alembic migrations against active database"
	@echo "  make test      - Run all pytest test suites"
	@echo "  make lint      - Run ruff linting checks"
	@echo "  make typecheck - Run mypy static type checking"
	@echo "  make shell-db  - Open psql shell in database container"
	@echo "  make install   - Install dependencies in current Python environment"

up:
	docker compose up -d db

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	$(VENV)/alembic upgrade head

test:
	$(VENV)/pytest -v

lint:
	$(VENV)/ruff check .

typecheck:
	$(VENV)/mypy app/ tests/

shell-db:
	docker compose exec db psql -U hkw -d hk_weather

install:
	pip install -e ".[dev]"

dashboard:
	$(VENV)/streamlit run app/dashboard/main.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info

