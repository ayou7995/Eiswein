# Eiswein — top-level operations.
#
# Two flavors of target:
#   * USER TARGETS  (install / start / stop / logs / update / uninstall)
#     drive the distributable Docker stack. These are the commands a
#     friend pulls down the README and runs.
#   * DEV TARGETS   (dev / test / lint / type / migrate / deps-*)
#     run the toolchain directly on the host so you can edit code
#     with hot reload.

.PHONY: help \
        install start stop logs update uninstall \
        dev lint format type test migrate \
        deps-update deps-sync

# ---------- User targets (distributable Docker stack) ----------------------

help:
	@echo "Eiswein — user commands"
	@echo "  make install     First-time interactive setup (writes .env + certs/)"
	@echo "  make start       Boot the stack in the background"
	@echo "  make stop        Shut the stack down"
	@echo "  make logs        Tail backend logs (Ctrl+C to leave)"
	@echo "  make update      git pull + rebuild + restart"
	@echo "  make uninstall   Destructive: stop, remove containers, delete .env + data/"
	@echo ""
	@echo "Eiswein — dev commands"
	@echo "  make dev         Foreground dev (Vite 5173 + uvicorn 8000)"
	@echo "  make test        pytest -v backend/tests"
	@echo "  make lint        ruff check"
	@echo "  make format      ruff format"
	@echo "  make type        mypy --strict app"
	@echo "  make migrate     alembic upgrade head"
	@echo "  make deps-update Regenerate backend/requirements.txt"
	@echo "  make deps-sync   pip-sync to backend/requirements.txt"

install:
	@python3 scripts/bootstrap.py

start:
	@docker compose up -d
	@echo ""
	@echo "Eiswein started. Open http://localhost:8080"
	@echo "(or https://localhost:8080 if you generated Schwab certs)."

stop:
	@docker compose down

logs:
	@docker compose logs -f eiswein

update:
	@echo "==> Pulling latest changes..."
	@git pull --ff-only
	@echo "==> Rebuilding image..."
	@docker compose build
	@echo "==> Restarting..."
	@docker compose up -d
	@echo "Update complete."

uninstall:
	@bash scripts/uninstall.sh

# ---------- Dev targets ----------------------------------------------------

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
	cd backend && uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 \
		--ssl-keyfile=local-key.pem --ssl-certfile=local-cert.pem
