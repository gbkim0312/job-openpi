.PHONY: up down test lint
up: ; cp -n .env.example .env 2>/dev/null || true; docker compose up --build
down: ; docker compose down
test: ; cd backend && python -m pytest
lint: ; cd backend && ruff check src tests
