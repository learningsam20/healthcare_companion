.PHONY: install test lint typecheck imports up down migrate seed smoke web api clean

install:
	uv sync
	npm --prefix apps/web install

test:
	./scripts/test.sh

lint:
	./scripts/lint.sh

typecheck:
	uv run mypy apps/api/app packages/py-common/sahyog_common
	npm --prefix apps/web run typecheck

imports:
	uv run lint-imports

up:
	./scripts/start.sh --profile minimal

down:
	./scripts/stop.sh

migrate:
	./scripts/migrate.sh

seed:
	./scripts/seed-users.sh
	./scripts/load-data.sh --sample

smoke:
	./scripts/smoke.sh

web:
	npm --prefix apps/web run dev

api:
	uv run uvicorn app.main:app --reload --app-dir apps/api --port 5706

clean:
	rm -rf .venv node_modules apps/web/node_modules apps/web/dist .pytest_cache .ruff_cache .mypy_cache
