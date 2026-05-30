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
        dev lint format format-check type test migrate verify \
        deps-update deps-sync

# ---------- User targets (distributable Docker stack) ----------------------

help:
	@echo "Eiswein — user commands"
	@echo "  make install     First-time interactive setup (writes .env + certs/)"
	@echo "  make start       Boot the stack in the background (rebuilds if source changed)"
	@echo "  make stop        Shut the stack down"
	@echo "  make logs        Tail backend logs (Ctrl+C to leave)"
	@echo "  make update      git pull + rebuild + restart"
	@echo "  make uninstall   Destructive: stop, remove containers, delete .env + data/"
	@echo ""
	@echo "Eiswein — dev commands"
	@echo "  make dev          Foreground dev (Vite 5173 + uvicorn 8000)"
	@echo "  make test         pytest -v backend/tests"
	@echo "  make lint         ruff check (backend + scripts)"
	@echo "  make format       ruff format (rewrites files)"
	@echo "  make format-check ruff format --check (CI-equivalent, read-only)"
	@echo "  make type         mypy --strict app"
	@echo "  make migrate      alembic upgrade head"
	@echo "  make verify       MANDATORY before git push — runs the full CI gate locally"
	@echo "  make deps-update  Regenerate backend/requirements.txt"
	@echo "  make deps-sync    pip-sync to backend/requirements.txt"

# Bootstrap venv lives in the repo (gitignored). Keeps bcrypt + zxcvbn
# out of the operator's system Python so a fresh-clone install doesn't
# leave packages behind. `make uninstall` deletes it.
BOOTSTRAP_VENV := .venv-bootstrap
BOOTSTRAP_PY   := $(BOOTSTRAP_VENV)/bin/python

# `--env-file /dev/null` skips compose's interpolation pass over .env.
# Why: bcrypt hashes contain literal `$`s ("$2b$12$...") which compose
# would treat as variable references, printing noisy WARNs and (worse)
# risking a silent substitution if the segment happens to match a shell
# env var. The container still receives every .env line literally via
# the `env_file: .env` directive inside docker-compose.yml.
COMPOSE := docker compose --env-file /dev/null

install: $(BOOTSTRAP_VENV)/.installed
	@$(BOOTSTRAP_PY) scripts/bootstrap.py

# Idempotent venv setup. ``.installed`` is a sentinel so re-running
# ``make install`` doesn't re-install bootstrap deps every time.
# The recipe depends on the bootstrap requirements file so a future
# version bump invalidates the sentinel and triggers a re-install.
$(BOOTSTRAP_VENV)/.installed: scripts/requirements.bootstrap.txt
	@echo "==> Setting up bootstrap venv ($(BOOTSTRAP_VENV))..."
	@test -d $(BOOTSTRAP_VENV) || python3 -m venv $(BOOTSTRAP_VENV)
	@$(BOOTSTRAP_PY) -m pip install --quiet --upgrade pip
	@$(BOOTSTRAP_PY) -m pip install --quiet -r scripts/requirements.bootstrap.txt
	@touch $(BOOTSTRAP_VENV)/.installed

# Always pass --build so a `git pull` followed by `make start` picks
# up source changes in the image. Docker's layer cache makes the
# no-op case (no source changed) cheap — typically ~5 seconds.
# Without --build, restarting only swaps the container against the
# *cached* image and silently runs old code.
start:
	@$(COMPOSE) up -d --build
	@echo ""
	@echo "Eiswein started. Open http://localhost:8080"
	@echo "(or https://localhost:8080 if you generated Schwab certs)."

stop:
	@$(COMPOSE) down

logs:
	@$(COMPOSE) logs -f eiswein

update:
	@echo "==> Pulling latest changes..."
	@git pull --ff-only
	@echo "==> Rebuilding + restarting..."
	@$(COMPOSE) up -d --build
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

# Read-only sibling of ``format`` — exits non-zero if anything would be
# reformatted. Mirrors the ``ruff format --check .`` step CI runs.
format-check:
	cd backend && ruff format --check .

type:
	cd backend && mypy --strict app

test:
	cd backend && pytest -v tests

migrate:
	cd backend && alembic upgrade head

# Pre-push gate — runs every check GitHub Actions runs, in the same
# order, so a green ``make verify`` means CI will go green too.
# AGENTS.md treats this as MANDATORY before any push to origin/main.
verify:
	@echo "==> [1/6] Backend lint (ruff check .)"
	@cd backend && ruff check .
	@echo "==> [2/6] Backend format (ruff format --check .)"
	@cd backend && ruff format --check .
	@echo "==> [3/6] Backend types (mypy --strict app)"
	@cd backend && mypy --strict app
	@echo "==> [4/6] Backend tests (pytest)"
	@cd backend && pytest -q --tb=short tests
	@echo "==> [5/6] Frontend lint + types + tests + build"
	@cd frontend && npm run lint && npx tsc --noEmit && npx vitest run && npm run build
	@echo "==> [6/6] Alembic migration smoke test (round-trip on a temp DB)"
	@cd backend && DATABASE_URL=sqlite:///./data/verify_smoke.db alembic upgrade head \
		&& DATABASE_URL=sqlite:///./data/verify_smoke.db alembic downgrade -1 \
		&& DATABASE_URL=sqlite:///./data/verify_smoke.db alembic upgrade head \
		&& rm -f ./data/verify_smoke.db
	@echo ""
	@echo "All checks passed. Safe to push."

dev:
	cd backend && uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000 \
		--ssl-keyfile=local-key.pem --ssl-certfile=local-cert.pem
