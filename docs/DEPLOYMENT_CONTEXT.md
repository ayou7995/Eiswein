# Eiswein — Deployment Context

> Paste this into Claude web (or any LLM) and ask: **"Given these constraints, compare deployment options for me — Oracle Cloud Free Tier ARM, Hetzner CX22, Fly.io, Railway, Render, AWS Lightsail, DigitalOcean Droplet, self-hosted Mac mini, etc. Recommend the best fit and why."**
>
> Date snapshot: 2026-04-27. Single-developer, single-user (admin only) personal app.

---

## 1. What Eiswein is

A **personal stock-market decision-support tool** (NOT automated trading). It analyses a user-managed watchlist with 12 technical indicators, produces daily buy/hold/reduce/exit recommendations, and tracks decision history. Inspired by Heaton's "Sherry" trading system. Human always makes final trades.

- **Users**: 1 (the dev/owner). No multi-tenant, no public signup. Admin login only.
- **Access pattern**: Owner reads dashboard once or twice a day on phone (often via mobile data, occasionally laptop). Daily summary email.
- **Latency budget**: relaxed (it's a daily-decision tool, not an HFT).
- **Uptime target**: best-effort. A few hours of downtime is annoying but not catastrophic.

---

## 2. Tech stack

### Backend
- **Python 3.12** + FastAPI 0.115 (`uvicorn[standard]==0.32.0`)
- **SQLAlchemy 2.0** + Alembic 1.13
- **SQLite** (WAL mode via SQLAlchemy event listener). DB file at `data/eiswein.db`.
- **APScheduler 3.10** (AsyncIOScheduler, in-process)
- **pandas 2.2 + numpy 2.1 + pyarrow 17** for indicator math (NO `pandas_ta` — pure-function indicator implementations, validated against fixtures)
- **yfinance 1.3** — primary price + macro fallback source (free, unauthenticated)
- **fredapi 0.5.2** — FRED macro data (requires free API key)
- **pandas-market-calendars 4.4** — NYSE calendar
- **Schwab OAuth (stub-ready)** — `app.datasources.schwab_*` with PKCE flow already implemented; only enabled when `SCHWAB_CLIENT_ID` + `SCHWAB_CLIENT_SECRET` configured. v1 deploys can run without it.
- **bcrypt 4.2 / cryptography 43 / python-jose 3.3 / zxcvbn / slowapi / structlog 24.4**
- **Test deps**: pytest 8.3, pytest-asyncio, httpx, freezegun
- **Lint/types**: ruff 0.6.9 + mypy 1.11 (strict)

### Frontend
- **React 18.3 + TypeScript 5.7** (strict mode, zero `any`)
- **Vite 5.4** + Tailwind 3.4 + PostCSS
- **TanStack Query 5.62** + react-router-dom 6.28 + react-hook-form 7.54
- **Zod 3.23** for runtime schema validation at every API boundary
- **lightweight-charts 4.2** (TradingView) + custom SVG charts
- **Vitest 2.1** + Testing Library

### Build artefact
- Multi-stage Docker image planned: Stage 1 Node → `npm run build` → static dist. Stage 2 Python 3.12-slim → install deps → copy backend + React build. FastAPI serves `dist/` as static files at `/` and API at `/api/v1/*`.
- Image NOT yet built — see §10 for what's still missing.

---

## 3. Code structure

```
backend/                                 116 Python files, 83 test modules
├── pyproject.toml                       ruff strict + mypy strict
├── requirements.in / requirements.txt   pip-tools managed
├── alembic.ini + alembic/versions/      14 migrations (0001..0014)
├── data/
│   ├── eiswein.db                       SQLite (WAL)
│   ├── cache/                           parquet cache for yfinance bulk frames
│   ├── backups/                         daily SQLite backups (sqlite3 `.backup`)
│   └── scheduler.lock                   fcntl.flock guard for APScheduler
└── app/
    ├── main.py                          FastAPI factory (`uvicorn app.main:create_app --factory`)
    ├── config.py                        pydantic-settings, env-only
    ├── api/v1/                          15 route modules (auth, watchlist, market, ticker,
    │                                    history, positions, settings, broker [Schwab],
    │                                    admin [backfill], import [broker CSV], data, indicators,
    │                                    health)
    ├── db/
    │   ├── models.py                    16 tables: User, AuditLog, Ticker, BrokerCredential,
    │   │                                Watchlist, DailyPrice, MacroIndicator, DailySignal,
    │   │                                TickerSnapshot, MarketSnapshot, MarketPostureStreak,
    │   │                                Position, SystemMetadata, Trade, BackfillJob
    │   ├── database.py                  WAL mode + connection pool config
    │   └── repositories/                15 repositories (one per aggregate)
    ├── datasources/                     base.DataSource ABC, factory, yfinance,
    │                                    fred, schwab_oauth + schwab_source, polygon (stub)
    ├── ingestion/                       Centralized orchestrator: ONE bulk yfinance call per
    │                                    daily_update; persists prices → recomputes indicators
    │                                    from DB; broker CSV importer (generic, Schwab adapter)
    ├── indicators/                      12 indicators as pure functions
    │                                    (market_regime/, direction/, timing/, macro/)
    │                                    NEVER call network — DataFrame in, IndicatorResult out
    ├── signals/                         direction.py + timing.py + market_posture.py +
    │                                    compose.py + entry_price.py + stop_loss.py +
    │                                    pros_cons.py (decision tables, no template narrator)
    ├── services/                        backfill_service, schwab_session, snapshot_write_mutex
    │                                    (threading.Lock), symbol_onboarding_service,
    │                                    trade_import_service
    ├── security/                        auth (JWT), encryption (AES-256-GCM column-level for
    │                                    Schwab refresh tokens), rate_limit (slowapi),
    │                                    middleware (CF-Connecting-IP validation,
    │                                    SecurityHeaders, RequestContext), error_handlers,
    │                                    log_sanitizer (redacts password/token/secret/key)
    └── jobs/                            APScheduler jobs: daily_update, backup, vacuum,
                                         email_dispatcher, schwab_token_refresh, token_reminder
                                         + scheduler.py with fcntl.flock guard

frontend/                                121 TS/TSX files
└── src/
    ├── pages/                           Dashboard, TickerDetail, Positions, History, Settings,
    │                                    Login (each with .test.tsx)
    ├── components/                      ~30 components: SignalBadge, PriceBar, charts/, modals,
    │                                    SnapshotStatusIcons (versioning), Pros/Cons lists, etc.
    ├── api/                             typed clients with Zod schemas (one file per resource)
    ├── hooks/                           useAuth, useWatchlist, query hooks
    ├── layouts/                         shell + nav
    └── lib/                             shared utilities + Zod constants
```

### Tests
- Backend: 83 pytest modules, ~625+ assertions; full DB integration tests against tmp SQLite (no mocks for DB layer per project rule).
- Frontend: ~120 vitest tests; happy-path + error-path coverage for each page.
- CI: `.github/workflows/ci.yml` runs ruff, mypy strict, pytest, eslint, tsc, vitest.

---

## 4. Database

- **SQLite, single file** (`data/eiswein.db`).
- **WAL mode** required (event listener forces `PRAGMA journal_mode=WAL` at engine connect).
- **Single writer**: enforced by `services/snapshot_write_mutex.py` (a `threading.Lock`) and uvicorn `--workers 1` invariant.
- 14 Alembic migrations applied; **schema is stable** for v1 deploy.
- Current dev DB ~1.5 years of data; entire `backend/data/` directory ~104 MB (DB + parquet cache + 1 backup). After 5 years estimate < 500 MB.
- Backups: `sqlite3.connect().backup()` → `data/backups/eiswein-YYYY-MM-DD.db` daily at 07:00 ET (job retains last 7 days).

---

## 5. Background jobs (APScheduler, in-process)

All jobs run in-process inside the same FastAPI uvicorn worker. Single instance enforced two ways: `--workers 1` + `fcntl.flock` on `data/scheduler.lock`. Timezone: `America/New_York`.

| Job                  | Cron (ET)              | What                                                                         |
|----------------------|------------------------|------------------------------------------------------------------------------|
| `daily_update`       | 06:30                  | One bulk `yf.download(symbols, threads=False)` call → persist DailyPrice → recompute indicators + signals from DB. Skips weekends + NYSE holidays via market calendar. |
| `backup`             | 07:00                  | SQLite online `.backup` → `data/backups/`. Retains 7 days.                   |
| `token_reminder`     | 09:15 (Mon-Fri)        | Email if Schwab refresh token < 5 days from expiry.                          |
| `vacuum`             | Sun 03:00 (1st of month) | `VACUUM` + `ANALYZE`.                                                      |
| `schwab_token_refresh` | every 20 min          | Refresh Schwab access token if Schwab is enabled (refresh tokens last 7 days, access tokens 30 min). |

**Implication for deploy**: the host MUST stay running 24/7 — serverless / cold-starting platforms break the scheduler.

---

## 6. External services + secrets

### Required at runtime
- `JWT_SECRET` — 64+ random chars (HS256)
- `ENCRYPTION_KEY` — 32-byte base64-url (AES-256-GCM for Schwab refresh tokens at column level)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` — bcrypt-hashed (12 rounds) admin password; seeded on first boot

### Optional
- `FRED_API_KEY` — free, used by macro indicators (DXY, FedFunds). App degrades gracefully if absent.
- `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/TO` — daily-summary email. App no-ops if unset.
- `SCHWAB_CLIENT_ID/SECRET/REDIRECT_URI` — broker OAuth. Routes register only if both set.
- `POLYGON_API_KEY` — stub interface; not used in v1.

### Network egress dependencies
- `query1.finance.yahoo.com` (yfinance)
- `api.stlouisfed.org` (FRED)
- `api.schwabapi.com` (Schwab; optional)
- SMTP relay (Gmail SMTP if Gmail App Password configured)

**Rationale for full env**: see `.env.example` (kept in repo).

---

## 7. Hard operational invariants (must survive any deploy choice)

1. **`uvicorn --workers 1`** — never raise. SQLite single-writer + APScheduler instance dedup require it.
2. **SQLite WAL mode** via event listener (not connect_args).
3. **One yfinance bulk call per daily_update** (`yf.download(" ".join(symbols), threads=False)`), never per-ticker.
4. **APScheduler protected by `fcntl.flock`** on a lock file inside `data/`.
5. **No plaintext secrets on disk** in production. Plan: SOPS + age. `age.key` lives at `/etc/eiswein/age.key` (chmod 600) or equivalent secret-store integration.
6. **httpOnly + SameSite=Lax cookies** for JWT (never localStorage).
7. **All API routes under `/api/v1/`**.
8. **Schwab refresh tokens AES-256-GCM encrypted** at column level in `BrokerCredential`.
9. **Rate limit keyed by `CF-Connecting-IP`** with Cloudflare IP-range validation middleware (relevant only if fronted by Cloudflare).
10. **Cold-start backfill** is a real feature: BackfillService can replay historical snapshots — moderate one-off CPU/network cost (a backfill of 2 years × 5 symbols takes a few minutes).

---

## 8. Resource profile

### Steady-state (idle / cron-only)
- **CPU**: < 5% of one ARM/x86 core. Mostly sleeping.
- **RAM**: ~150–250 MB resident (Python + pandas + uvicorn). Spikes to ~600–800 MB during `daily_update` while pandas DataFrames are alive.
- **Disk**: < 1 GB total (DB + cache + backups).
- **Network**: a few MB/day (one yfinance bulk fetch + a handful of FRED calls + occasional dashboard fetch).

### Burst (daily_update window 06:30–06:33 ET)
- **CPU**: 1 core pegged for ~30 sec to a few minutes (depends on watchlist size; capped at 100 symbols).
- **RAM**: ~600–800 MB.
- **Network**: ~5–20 MB egress to Yahoo + FRED.

### Burst (manual backfill, e.g. onboarding 2 years × 30 symbols)
- **CPU**: 1 core for ~10–30 minutes.
- **RAM**: still bounded ~800 MB.
- **Network**: ~50–200 MB.

### Outbound bandwidth/month
- Steady-state: low single-digit GB/month including phone dashboard fetches.
- Spikes: a few hundred MB if multiple backfills run.

**Conclusion**: 1 vCPU, 1 GB RAM is enough; 2 GB is comfortable. ARM is fine (yfinance / pandas / numpy / pyarrow all ship arm64 wheels for Python 3.12). 10 GB disk is plenty.

---

## 9. Network / security posture

### Planned (per `docs/IMPLEMENTATION_PLAN.md` Phase 7)
- **Cloudflare Named Tunnel** + `cloudflared` sidecar container — VM has zero public ports (only outbound to CF edge).
- **Cloudflare Access** — Google-OAuth-only policy in front of the app (first auth layer).
- **App-level JWT** — second auth layer; verifies CF Access JWT header as belt-and-suspenders.
- **VM firewall**: SSH (22) only, from owner's IP. No public 80/443.
- **Boot volume encryption** enabled on VM.

### Already implemented in code
- All security headers (`SecurityHeadersMiddleware`)
- Login throttling (5 fails / 15 min IP lock + global 20/min alert)
- Rate limiting via slowapi keyed off `CF-Connecting-IP` (with CF IP-range validation middleware ready)
- bcrypt password hashing (12 rounds) + zxcvbn strength validation
- Structlog log sanitizer (redacts `password|token|secret|key`)
- AES-256-GCM column-level encryption for Schwab refresh tokens
- Audit log table + repository

### What this means for hosting choices
- The app does NOT need to terminate TLS itself in the canonical plan — Cloudflare Tunnel does it.
- If a candidate platform forces public ingress (e.g. Fly.io's anycast IPs, Render's public domain), we still keep CF Access in front via DNS, but lose the "no public port" advantage.

---

## 10. What's already in the repo vs. what's NOT yet built

### Already in repo
- All backend code (15 routes, 16 tables, 14 migrations, 12 indicators, 5 jobs, security stack)
- All frontend code (6 pages, ~30 components, full Zod validation)
- Operational scripts (`scripts/`):
  - `setup_secrets.sh` — interactive SOPS + age onboarding
  - `set_password.py` — generate bcrypt hash for `ADMIN_PASSWORD_HASH`
  - `reset_password_offline.py` — reset admin password via SSH on the VM
  - `rotate_age_key.sh` — rotate SOPS age key
  - `rotate_secrets.py` — rotate JWT_SECRET / ENCRYPTION_KEY (re-encrypts BrokerCredential)
  - `dev_curl.sh`, `dev_reset_lockout.py`, `generate_indicator_fixtures.py`
- `.github/workflows/ci.yml` — test + lint pipeline
- `.gitleaks.toml`, `.gitignore`, `.env.example`, `README.md`, `Makefile`

### Not yet built (Phase 7 of the original plan)
- `Dockerfile` (multi-stage Node → Python 3.12-slim, ARM-compatible, target < 300 MB)
- `docker-compose.yml` (single service + cloudflared sidecar; pin `--workers 1`)
- `.dockerignore`
- `docker-entrypoint.sh` (SOPS-decrypt → exec uvicorn; mounts `/tmp` as tmpfs)
- `secrets/eiswein.enc.yaml` + `.template`
- `.github/workflows/deploy.yml` (build multi-arch image → push to `ghcr.io`; Watchtower on VM auto-pulls)
- VM provisioning (install Docker, cloudflared, age key)
- Cloudflare Tunnel config + Access application
- Image healthcheck + NTP setup

---

## 11. Original deployment plan (reference)

From `docs/IMPLEMENTATION_PLAN.md` Phase 7:

- **Target VM**: Oracle Cloud Free Tier (ARM Ampere A1, 24 GB RAM "Always Free") OR Hetzner CX22 backup (~€5/mo).
- **Pattern**: single Docker container + cloudflared sidecar via docker-compose; multi-stage build pinned to `python:3.12-slim-bookworm`; image target < 300 MB.
- **CD**: GitHub Actions → multi-arch (`linux/amd64` + `linux/arm64`) → `ghcr.io/ayou7995/eiswein:latest` → Watchtower on VM auto-pulls.
- **Secrets**: SOPS + age, age key on VM at `/etc/eiswein/age.key` chmod 600.
- **Auth**: Cloudflare Access (Google OAuth, owner only) + app JWT (CF Access JWT verified as second layer).

---

## 12. The owner's preferences / context (relevant to the deploy choice)

- Single-developer side project. Wants it to "just run". Low-maintenance over cleverness.
- Prefers paying $0/month if Free Tier holds; ceiling tolerance ~$10/mo if it buys real reliability or simplicity.
- Already comfortable with CLI, Docker, GitHub Actions. Comfortable with Cloudflare. Less keen on managing a full Linux VM if a managed alternative is comparably secure.
- Lives in Asia (Taiwan timezone; data sources are US). Latency from VM region to phone is mostly irrelevant since 1 user + few requests/day.
- Cares strongly about: secrets-at-rest, no public ports, daily SQLite backups not being lost.
- Does NOT need: scale-out, blue/green, multi-region, on-call alerting beyond email.

---

## 13. The questions to answer

Given everything above:

1. **Which deploy target is best fit?** (Compare at minimum: Oracle Cloud Free Tier ARM, Hetzner CX22, Fly.io, Railway, Render, Vercel-style platforms, AWS Lightsail/EC2 t4g.small, DigitalOcean Droplet, Mac mini at home + Cloudflare Tunnel.)
2. **What are the trade-offs** for each on: cost, maintenance burden, secret management, persistent volume for SQLite + backups, scheduler-friendliness (no cold starts), ARM support, region/latency, vendor risk?
3. **Where does the original plan fall short** if anywhere? E.g. is Oracle Free Tier still reliable in 2026? Are there cheaper/simpler options I haven't considered?
4. **Concrete recommendation** — pick one primary + one fallback, and explain why for THIS app, THIS owner.
5. **Migration path** — what's the minimum set of changes (Dockerfile shape, secret strategy, SQLite persistence, cron survival) to land on the chosen target?

> Hard constraints: persistent disk, always-on (24/7 scheduler), ARM or x86 OK, image up to 300 MB, no public 80/443 (Cloudflare Tunnel preferred). Do not recommend serverless/scale-to-zero — the in-process scheduler forbids it.
