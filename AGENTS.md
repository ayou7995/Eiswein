# AGENTS.md — Maintenance Contract for Distribution

Eiswein is shipped to **1–3 trusted users** as a private repo they
clone and run via `make install && make start` against a Docker
stack. This file captures every place a future code change must
also update so the next `make update` keeps working on their
machine.

**Treat this file as a checklist before merging.** A small
incidental edit that breaks the install flow is much worse for a
non-developer friend than for a maintainer with the full toolchain
in their head.

---

## ⚠️ MANDATORY pre-push gate

**Before EVERY `git push origin main` (and before opening any PR),
run `make verify` from the repo root and confirm it exits 0.**

```sh
make verify
```

`make verify` runs the exact same six checks that GitHub Actions
runs in CI, in the same order:

1. `ruff check .`            (backend lint)
2. `ruff format --check .`   (backend formatting — **this is what
   tripped us in commit a580177**; lint alone does not catch it)
3. `mypy --strict app`       (backend types)
4. `pytest tests`            (backend test suite)
5. `npm run lint && npx tsc --noEmit && npx vitest run && npm run build`
   (frontend lint + types + tests + production build)
6. `alembic upgrade head && downgrade -1 && upgrade head`
   (migration round-trip on a throwaway DB)

If any step fails locally, **fix it before pushing** — don't push
"and let CI tell me." CI failures on `main` show up in the
collaborator list and block the next person's pull.

Skipping `make verify` is allowed only when the change touches
*nothing* CI runs (e.g. editing this file's prose, adding a doc-
only `.md`). Even then, when in doubt: run it.

---

## Principles

1. **English is the canonical doc source.** Every user-facing
   document ships in two files: `<name>.md` (English) and
   `<name>_zhTW.md` (Traditional Chinese). When you edit one, edit
   the other in the same commit. zh-TW translates from EN; if a
   feature isn't yet documented in EN, do not write zh-TW first.
2. **`.env.example` and `scripts/bootstrap.py` move together.**
   Every required env var must appear in both; every optional var
   that the wizard can prompt for needs a branch in `bootstrap.py`
   plus a corresponding row in `.env.example`.
3. **The container is the source of truth at runtime.** If the
   change affects how the app boots, persists data, or accepts
   external traffic, update both `Dockerfile` and
   `docker-compose.yml`. Smoke-test `docker compose build` before
   pushing.
4. **No breaking change without the release checklist.** Section
   "Release checklist" below must be walked manually before any tag
   or push that crosses a migration / breaking config change.

---

## Trigger table — what to update when you change X

| When you change… | You MUST also update… |
|---|---|
| Add a required env var | `.env.example` + `scripts/bootstrap.py` (prompt + write) + `README.md` § 進階設定 / Advanced |
| Add an optional env var | `.env.example` + `scripts/bootstrap.py` (skip-default branch) + `docs/SETUP_GUIDE.md` |
| Add an auto-generated secret | `scripts/bootstrap.py` only |
| Rename / remove an env var | Same as above + add a note to `README.md` § Update so existing users know to re-run bootstrap |
| Add / bump a bootstrap-time Python dep | `scripts/requirements.bootstrap.txt` — the Makefile's `.venv-bootstrap/.installed` sentinel depends on this file so it auto-rebuilds on next `make install`. Re-run `make uninstall && make install` once locally to confirm the venv rebuild path still works |
| Bump Python version | `Dockerfile` (`FROM python:`) + `pyproject.toml` `target-version` |
| Bump Node version | `Dockerfile` (`FROM node:`) + `frontend/package.json` `engines` if set |
| Add an APScheduler job | `README.md` § Automatic scheduling + zh-TW twin |
| Change `daily_update` time | `README.md` § Automatic scheduling + bootstrap explainer |
| Change Schwab redirect URI | `scripts/bootstrap.py` `HOST_PORT` / formatted URI + `docs/SETUP_GUIDE.md` Schwab section |
| Change container outer port | `docker-compose.yml` ports + `Makefile` `start` echo + `scripts/bootstrap.py` `HOST_PORT` + `README.md` quickstart |
| Add a Makefile target | `Makefile` `help` block + `README.md` § Daily operations |
| Remove a Makefile target | Same as above + comment to migrate users in `README.md` § Update |
| Add an Alembic migration | Nothing — entrypoint runs `alembic upgrade head` automatically; but if the migration is destructive add a backup note to README |
| Add a new external dependency (Redis, Postgres, …) | `docker-compose.yml` (new service) + `Dockerfile` if compiled deps + `bootstrap.py` to gather any credentials + both READMEs |
| Add a new SPA route | Nothing — `StaticFiles(html=True)` falls back to `index.html` automatically. But if it's deep-linked from email, ensure the link is `https://localhost:8080/...` (FRONTEND_URL) |
| Change cookie semantics (Secure / SameSite / Domain) | `scripts/bootstrap.py` (COOKIE_SECURE branch) + `docs/SETUP_GUIDE.md` Troubleshooting |
| Remove a feature that had a `.env` flag | Drop the var from `.env.example` AND from `bootstrap.py` AND mention in `README.md` § Update |
| Add a new emailing job | Update `docs/SETUP_GUIDE.md` SMTP section + zh-TW twin |
| Change SMTP defaults | `bootstrap.py` Gmail / Mailpit branches + SETUP_GUIDE |
| Touch any user-facing zh-TW string in the app | No doc impact, but verify the English commit doesn't break the language assumption documented here |

---

## File-pair sync map

Whenever the left changes, the right must change in the same commit
(and vice versa):

```
README.md                          ↔ README_zhTW.md
docs/SETUP_GUIDE.md                ↔ docs/SETUP_GUIDE_zhTW.md
NOTICE.md (the EN top half)        ↔ NOTICE.md (the zh-TW bottom half)
.env.example                       ↔ scripts/bootstrap.py
docker-compose.yml                 ↔ Dockerfile
backend/app/jobs/scheduler.py      ↔ README (§ Automatic scheduling)
backend/app/config.py Settings     ↔ .env.example + bootstrap.py
```

---

## Release checklist

Before pushing to `origin/main` after a change that touches anything
in the trigger table or the file-pair sync map, walk this list on
your own laptop:

0. **`make verify` first.** All six CI steps must pass locally
   before you touch any of the manual steps below. If `make verify`
   fails, stop and fix — none of the rest matters until CI would
   pass.
1. **Stash personal state** so it doesn't influence the run:
   ```sh
   mv .env .env.bak 2>/dev/null
   mv data data.bak 2>/dev/null
   mv certs certs.bak 2>/dev/null
   ```
2. **Uninstall idempotency:** `make uninstall` (should print "Source
   code is untouched" and refuse if you cancel).
3. **Install:** `make install` and walk the prompts — confirm every
   integration branch (skip all, then Gmail, then Mailpit, then
   Schwab) over multiple bootstrap runs.
4. **Start:** `make start`. Verify:
   - `curl http://localhost:8080/api/v1/health` → 200.
   - Browser opens at `http://localhost:8080`, login works, sidebar
     renders.
5. **Logs:** `make logs` — confirm structured JSON, no scary stack
   traces in startup.
6. **Schedule sanity:** check the log line `startup_catchup="scheduled"`
   appears, and that `daily_update` runs (look for
   `daily_update_complete` within a few minutes).
7. **Migration safety:** add a watchlist symbol, `make stop`, then
   `make start` — verify the symbol survives.
8. **Update flow:** `git pull` (will be a no-op locally), `make
   update` — confirm `docker compose build` actually rebuilds, no
   data loss.
9. **Final uninstall:** `make uninstall`, then restore your stashed
   state:
   ```sh
   mv .env.bak .env
   mv data.bak data
   mv certs.bak certs
   ```
10. **Doc spot-check:** open `README.md`. Does every command shown
    still work? Are env var names current? Has any screenshot
    drifted? Repeat for `README_zhTW.md`.

If any step fails, fix before merging. If a step is now wrong
because the change intentionally broke it (e.g. you renamed a
target), update README and re-run from step 1.

---

## What this file is NOT

- Not a code review guide — that's part of normal PR practice.
- Not a CI spec — these checks are manual. A future CI job that
  automates step 4-7 would be welcome but is out of scope.
- Not a security policy — see CLAUDE.md and the staff review docs.

---

## Quick reference

- Distributable port: **8080** (host) → 8000 (container)
- Friend access mode: invited GitHub read-only collaborator on
  private repo
- Bootstrap deps: auto-installed by `make install` into `.venv-bootstrap/` (per `scripts/requirements.bootstrap.txt`); system Python is never touched
- Mailpit profile: `COMPOSE_PROFILES=email make start`
