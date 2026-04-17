.PHONY: help deps-update deps-sync lint format type test migrate dev

help:
	@echo "Eiswein dev targets:"
	@echo "  deps-update   - regenerate requirements.txt via pip-compile"
	@echo "  deps-sync     - pip-sync backend/requirements.txt (install pinned)"
	@echo "  lint          - ruff check backend/ scripts/"
	@echo "  format        - ruff format backend/ scripts/"
	@echo "  type          - mypy --strict backend/"
	@echo "  test          - pytest -v backend/tests"
	@echo "  migrate       - alembic upgrade head"
	@echo "  dev           - uvicorn backend.app.main:app --reload"

deps-update:
	cd backend && pip-compile --generate-hashes --output-file=requirements.txt requirements.in
	cd backend && pip-audit -r requirements.txt || true

deps-sync:
	cd backend && pip-sync requirements.txt

lint:
	cd backend && ruff check .
	cd backend && ruff check ../scripts

format:
	cd backend && ruff format .
	cd backend && ruff format ../scripts

type:
	cd backend && mypy --strict app

test:
	cd backend && pytest -v tests

migrate:
	cd backend && alembic upgrade head

dev:
	cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
