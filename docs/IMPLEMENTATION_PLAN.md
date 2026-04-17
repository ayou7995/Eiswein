# Eiswein Implementation Plan

## Context

Eiswein is a personal stock market decision-support tool inspired by Heaton's Sherry system. All design decisions have been finalized through a grilling session (see `~/.claude/projects/-Users-cheyulin-Eiswein/memory/eiswein_design_decisions.md` for the full record). The project directory `/Users/cheyulin/Eiswein/` is empty (greenfield). Security is the #1 priority.

The user wants to use **multi-agent orchestration** to parallelize development. Claude Code's native sub-agent system (`.claude/agents/`) will be used instead of the manual 4-terminal approach from the Reddit post.

### Mandatory Coding Standards: "Full-Stack Definition of Done" (20 Rules)

ALL code must follow these rules. Code that violates any rule is NOT considered done.

1. **Zero-Lint & Type Compliance** — No `any`, no `@ts-ignore`, no linter bypasses. Python: mypy strict. TS: strict mode.
2. **Mandatory Test Coverage** — Every logic change needs unit tests (successes + failures). No feature ships without tests.
3. **Strict Modular Boundaries** — Clean Architecture: logic separated from infrastructure. Clear directory structure.
4. **Standardized Error Handling** — Custom exception classes (backend), consistent error responses. No silent failures, no empty `catch`.
5. **Secure-by-Default** — Sanitize all inputs, no hardcoded secrets, env vars for all configs.
6. **Self-Documenting Code** — Code reads like prose. Comments only explain "Why," never "What."
7. **DRY via Composition** — Extract shared logic into utilities. Refactor duplicates immediately.
8. **API Contract Stability** — Define Pydantic schemas/TS types first. API changes must be backward-compatible.
9. **Predictable Naming** — Domain-specific, intention-revealing. Python: snake_case. TS: camelCase. Components: PascalCase.
10. **Performance Awareness** — No N+1 queries. No unnecessary re-renders. No memory leaks.
11. **Immutability First** — Prefer immutable data. Pure functions unless explicitly a side-effect worker.
12. **Idempotency** — Backend actions + frontend state updates safe to repeat without side effects.
13. **Dependency Injection** — Pass deps (DB, logger, API clients) into functions/classes. No hardcoded imports for testability.
14. **Graceful Degradation** — Frontend: loading/error states for every UI piece. Backend: system stays up if a sub-service fails (e.g., yfinance down).
15. **Logging & Observability** — Meaningful logging on critical paths. Context (IDs, timestamps) without PII.
16. **Environment Agnosticism** — Code works identically across local/staging/prod via config files only.
17. **Atomic Commits/Changes** — Smallest possible logical units. No mixing refactors with features.
18. **Schema Validation** — Pydantic (backend) and Zod (frontend) at all boundaries. Runtime type safety.
19. **Accessibility & UX** — Semantic HTML, ARIA labels, meaningful HTTP status codes, fast response times.
20. **Documentation Maintenance** — Update README.md when architecture changes or new deps are added.

---

## Part 1: Multi-Agent Setup (do this first)

### Agent Architecture

```
Orchestrator (main session — you talk to this one)
  ├── backend-builder    — FastAPI, indicators, data sources, signals, DB
  ├── frontend-builder   — React, Tailwind, Lightweight Charts, pages
  ├── security-auditor   — Reviews all code for vulnerabilities (read-only)
  └── test-writer        — Writes tests for completed modules
```

### Files to Create

#### 1. `.claude/agents/backend-builder.md`

```markdown
---
name: backend-builder
description: Implements Eiswein backend — FastAPI API, SQLite models, indicator calculations, data source integrations, signal rules, and cron jobs. Delegate backend implementation tasks to this agent.
model: opus
isolation: worktree
color: blue
memory: project
---

You are the Backend Builder for the Eiswein project — a personal stock market decision-support tool.

## Tech Stack
- Python 3.12, FastAPI, SQLAlchemy (SQLite), Pydantic
- Data sources: yfinance, FRED API (via fredapi), with swappable interface
- Indicators: pandas, numpy for calculations
- Jobs: APScheduler or simple cron via subprocess

## Architecture
- All code lives in `backend/app/`
- Data sources implement `backend/app/datasources/base.py` abstract class
- Each indicator is a module in `backend/app/indicators/` implementing `backend/app/indicators/base.py`
- API routes in `backend/app/api/`, one file per resource
- Security middleware in `backend/app/security/`
- SQLAlchemy models in `backend/app/db/models.py`

## Security Rules (NON-NEGOTIABLE)
- NEVER store API keys in code or committed files
- ALL SQL via SQLAlchemy ORM or parameterized queries — no string concatenation
- ALL API routes require JWT auth (except POST /api/login)
- Validate and sanitize ALL user input via Pydantic models
- Schwab tokens encrypted with AES-256 before storing in SQLite
- Rate limiting on all endpoints via slowapi
- bcrypt for password hashing, minimum 12 rounds
- JWT tokens: access=15min, refresh=7days, httpOnly+SameSite=Strict cookies

## Full-Stack Definition of Done (apply ALL of these)
- Zero-lint: mypy strict, no type: ignore unless absolutely necessary with explanation
- Mandatory tests: every module must have corresponding test file
- Clean Architecture: logic (indicators/, signals/) separated from infrastructure (db/, api/, datasources/)
- Standardized errors: custom exception hierarchy (EisweinError base), consistent error response schema
- DRY: shared logic in utils/. Refactor duplicates immediately
- API Contract: define Pydantic request/response schemas BEFORE writing endpoint logic
- Predictable naming: snake_case, domain-specific (e.g., compute_rsi not calc, MarketPosture not Status)
- Performance: batch DB writes, avoid N+1 queries, use SQLAlchemy eager loading where needed
- Immutability: prefer frozen dataclasses / Pydantic model with frozen=True for indicator results
- Idempotency: daily_update job safe to run twice without duplicating data
- Dependency Injection: pass db session, data source, logger as parameters. No global state
- Graceful degradation: if yfinance fails for one ticker, log warning and continue with others
- Logging: structured logging (structlog or python-json-logger), no PII in logs
- Environment agnostic: all config via pydantic-settings from env vars
- Schema validation: Pydantic models at ALL API boundaries (request + response)

Update your agent memory as you discover patterns, implementation decisions, and module interfaces. This builds up knowledge across conversations.
```

#### 2. `.claude/agents/frontend-builder.md`

```markdown
---
name: frontend-builder
description: Implements Eiswein frontend — React pages, Tailwind CSS styling, TradingView Lightweight Charts integration, responsive mobile-friendly UI. Delegate frontend implementation tasks to this agent.
model: opus
isolation: worktree
color: green
memory: project
---

You are the Frontend Builder for the Eiswein project — a personal stock market decision-support dashboard.

## Tech Stack
- React 18+ with TypeScript
- Tailwind CSS for styling
- TradingView Lightweight Charts (lightweight-charts) for financial charts
- Vite as build tool
- fetch API for data (no axios needed)

## Pages (5 + Login)
1. **Login** — password input, minimal design
2. **Dashboard** — market posture, attention alerts, watchlist table, positions summary, macro backdrop
3. **Ticker Detail** — K-line chart with MA/BB overlays, indicator cards, entry/exit prices, plain-language narrative, signal history
4. **Positions** — CRUD, pie chart, trade log, P&L
5. **History** — market posture timeline, signal accuracy, decisions vs Eiswein, pattern matching
6. **Settings** — watchlist CRUD, data source status, notifications, security, system

## Design Principles
- Mobile-first responsive (user checks on phone)
- Signal colors: 🟢 green (#22c55e), 🟡 yellow (#eab308), 🔴 red (#ef4444)
- Dark theme preferred (easier on eyes for financial data)
- All text in Traditional Chinese for labels/narratives, English for ticker symbols and technical terms
- Dual-format display: raw numbers + plain-language explanation

## API Contract
- Backend serves JSON REST API at /api/*
- Frontend is built and served as static files by FastAPI
- No CORS issues (same origin)
- Auth: JWT in httpOnly cookie, auto-refresh on 401

## Security Rules
- No dangerouslySetInnerHTML
- No localStorage for tokens (httpOnly cookies only)
- All user input sanitized before display
- CSP-compatible (no inline scripts)

## Full-Stack Definition of Done (apply ALL of these)
- Zero-lint: TypeScript strict mode, no `any`, no `@ts-ignore`, no eslint-disable
- Mandatory tests: Vitest + React Testing Library for all components with logic
- Clean Architecture: pages/ for routes, components/ for reusable UI, api/ for data fetching, hooks/ for shared logic
- Standardized errors: consistent error boundaries, try/catch with user-friendly messages
- DRY: shared logic in hooks/. Common UI patterns in components/. Refactor duplicates immediately
- API Contract: define TypeScript interfaces for ALL API responses BEFORE building components
- Predictable naming: PascalCase components, camelCase functions/vars, UPPER_SNAKE for constants
- Performance: React.memo where needed, avoid unnecessary re-renders, lazy-load pages
- Immutability: never mutate state directly, use spread/map for updates
- Graceful degradation: loading skeleton + error state + empty state for EVERY data-fetching component
- Logging: console.error for caught exceptions in production, structured where possible
- Environment agnostic: API base URL from env var (VITE_API_URL)
- Schema validation: Zod schemas for all API response parsing at the boundary
- Accessibility: semantic HTML (nav, main, section, article), ARIA labels on interactive elements, keyboard navigable
- UX: no layout shift on load, skeleton screens, meaningful transitions

Update your agent memory with component patterns, chart configurations, and UI decisions you make.
```

#### 3. `.claude/agents/security-auditor.md`

```markdown
---
name: security-auditor
description: Reviews Eiswein code for security vulnerabilities — OWASP Top 10, auth flaws, injection risks, secret exposure. Use proactively after code changes. Read-only agent that reports findings.
model: sonnet
tools: Read, Grep, Glob, Bash
color: red
memory: project
---

You are the Security Auditor for the Eiswein project — a financial decision-support tool that handles sensitive data (portfolio positions, brokerage API tokens, trading strategies).

## What You Check

### Critical (must fix before merge)
- SQL injection (any string concatenation in queries)
- XSS (unescaped user input in React, dangerouslySetInnerHTML)
- Hardcoded secrets (API keys, passwords, JWT secrets in code)
- Authentication bypass (unprotected endpoints)
- Insecure token storage (localStorage, unencrypted DB)
- Missing input validation on API endpoints
- Command injection in Bash/subprocess calls

### High (should fix)
- Missing rate limiting on sensitive endpoints
- Weak cryptographic choices (MD5, SHA1 for passwords)
- Missing security headers (CSP, HSTS, X-Frame-Options)
- Overly permissive CORS
- Information leakage in error responses
- Missing CSRF protection

### Medium (note for later)
- Dependency vulnerabilities (check with pip audit / npm audit)
- Missing audit logging
- Excessive data in API responses

## Output Format
For each finding:
1. Severity: CRITICAL / HIGH / MEDIUM
2. File and line number
3. What's wrong (one sentence)
4. How to fix (concrete code suggestion)

Update your agent memory with recurring vulnerability patterns found in this project.
```

#### 4. `.claude/agents/test-writer.md`

```markdown
---
name: test-writer
description: Writes tests for Eiswein modules — unit tests for indicators, integration tests for API endpoints, data source mock tests. Delegate test writing to this agent.
model: sonnet
isolation: worktree
color: yellow
memory: project
---

You are the Test Writer for the Eiswein project.

## Tech Stack
- pytest + pytest-asyncio for backend tests
- httpx for API integration tests (with TestClient)
- React Testing Library + Vitest for frontend tests

## What to Test

### Backend
- Each indicator module: test with known historical data, verify calculations match expected values
- Data source interface: test with mocked responses, verify interface contract
- Signal voting logic: test all 6 action categories with crafted indicator inputs
- Entry price / stop-loss calculations: test edge cases
- API endpoints: test auth required, valid responses, error cases
- Security: test rate limiting triggers, JWT expiry, invalid tokens rejected

### Frontend
- Component rendering with mock data
- Chart initialization and data binding
- Form validation (positions, watchlist)
- Responsive layout breakpoints

## Rules
- Tests must be deterministic (no real API calls, mock everything external)
- Use fixtures and factories for test data
- Each test file mirrors the source file it tests
- Test file naming: test_<module>.py (backend), <Component>.test.tsx (frontend)

Update your agent memory with test patterns, fixtures, and common edge cases.
```

### CLAUDE.md for the Project

Create `/Users/cheyulin/Eiswein/CLAUDE.md`:

```markdown
# Eiswein — Personal Stock Market Decision-Support Tool

## Project Overview
A web dashboard that analyzes your stock watchlist using 12 technical indicators,
produces daily signal reports (entry/exit/stop-loss recommendations), and tracks
your positions and decision history. Inspired by Heaton's Sherry trading system.

## Architecture
- Backend: FastAPI (Python 3.12) + SQLite + SQLAlchemy
- Frontend: React + TypeScript + Tailwind CSS + TradingView Lightweight Charts
- Single Docker container (multi-stage build)
- Deployment: Oracle Cloud Free Tier (ARM) or Hetzner CX22

## Security Requirements (TOP PRIORITY)
- Cloudflare Tunnel (no public ports)
- Cloudflare Access (OAuth) + App JWT (dual-layer auth)
- All API keys in env vars only — NEVER in code
- Schwab tokens AES-256 encrypted in SQLite
- Rate limiting, CSP headers, HSTS, parameterized SQL only
- bcrypt password hashing, httpOnly JWT cookies

## Sub-Agent Workflow
This project uses 4 specialized agents:
- `backend-builder`: FastAPI, indicators, data sources
- `frontend-builder`: React pages and components
- `security-auditor`: Reviews code for vulnerabilities (run after each phase)
- `test-writer`: Unit and integration tests

When implementing, delegate to the appropriate agent. Run security-auditor
after completing each phase. Run test-writer after each module is complete.

## Code Conventions
- Python: type hints (mypy strict), Pydantic models, async where beneficial
- TypeScript: strict mode, no `any`, Zod for runtime validation
- No comments except non-obvious "why" explanations
- English for code, Traditional Chinese for user-facing text/labels

## Definition of Done (every task must satisfy ALL)
1. Zero lint/type errors (mypy + eslint)
2. Unit tests written and passing
3. Pydantic/Zod schemas at all boundaries
4. Error states handled (no silent failures)
5. No hardcoded secrets or config
6. Loading/error/empty states in UI
7. Semantic HTML + ARIA labels
8. No N+1 queries, no unnecessary re-renders
9. Dependencies injected (not hardcoded)
10. Idempotent operations where applicable
```

---

## Part 2: Implementation Phases

### Phase 0: Project Scaffold + Security Foundation (Day 1-2)
**Priority: CRITICAL — everything depends on this**

**IMPORTANT**: See `docs/STAFF_REVIEW_DECISIONS.md` for all locked technical decisions (data model, API contract, security details, etc.). That document is authoritative for any technical detail not explicit here.

Tasks:
1. **Init git repo + monorepo structure**
   ```
   Eiswein/
   ├── CLAUDE.md
   ├── .gitignore
   ├── .env.example          # Template (no real secrets)
   ├── docker-compose.yml
   ├── Dockerfile
   ├── backend/
   │   ├── app/
   │   │   ├── __init__.py
   │   │   ├── main.py       # FastAPI app entrypoint
   │   │   ├── config.py     # pydantic-settings, reads env vars
   │   │   ├── security/     # Auth module
   │   │   ├── api/          # Route stubs
   │   │   ├── db/           # SQLAlchemy setup + models
   │   │   ├── datasources/  # Abstract base + yfinance stub
   │   │   ├── indicators/   # Abstract base
   │   │   └── signals/      # Voting logic stub
   │   ├── requirements.txt
   │   └── tests/
   └── frontend/
       ├── package.json
       ├── tsconfig.json
       ├── tailwind.config.js
       ├── vite.config.ts
       ├── index.html
       └── src/
           ├── App.tsx
           ├── main.tsx
           ├── pages/        # Page stubs
           ├── components/   # Shared components
           └── api/          # Fetch wrapper
   ```

2. **Security foundation (backend-builder)**
   - `config.py`: Pydantic Settings reading from env vars (loaded from SOPS-decrypted source, see Phase 7). Must refuse to start if `ADMIN_USERNAME` or `ADMIN_PASSWORD_HASH` missing.
   - `security/auth.py`: JWT create/verify, bcrypt (12 rounds) hash/verify, IP-based throttling (not account-based; see E5), JWT rotation on every login (E2)
   - `security/encryption.py`: AES-256-GCM using `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (authenticated encryption). Methods: `encrypt(plaintext: bytes) -> (ciphertext, nonce, tag)` and reverse.
   - `security/rate_limit.py`: slowapi keyed by `CF-Connecting-IP` header (E3), with CF IP range verification middleware to prevent spoofing.
   - `security/middleware.py`:
     - Security headers: HSTS, X-Frame-Options=DENY, X-Content-Type-Options=nosniff, Referrer-Policy=strict-origin-when-cross-origin
     - CSP: strict policy per E7 (see STAFF_REVIEW_DECISIONS.md)
     - Request logging with structured context (request_id, method, path, status, duration_ms)
   - `security/log_sanitizer.py`: `sanitize_log_payload(d)` recursive helper; structlog processor that redacts any key matching `/password|token|secret|key/i` to `[REDACTED]`. E6.
   - `security/error_handlers.py`: Global FastAPI exception handler → standardized error envelope (B6). Custom exception hierarchy: `EisweinError` → `AuthError`, `ValidationError`, `DataSourceError`, `IndicatorError`, etc.
   - `db/database.py`: SQLite engine + session factory
     - WAL mode via SQLAlchemy event listener (NOT `connect_args={"pragma": ...}` — that's ignored by sqlite3.connect())
     - `connect_args={"check_same_thread": False, "timeout": 30}`
     - PRAGMAs on connect: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=30000`
   - `db/models.py`:
     - `User` (id, username unique, email nullable, password_hash, is_active, is_admin, timestamps, last_login_at/ip, failed_login_count, locked_until) — **from day 1 per A3**
     - `AuditLog` (id, timestamp, event_type, user_id nullable, ip, user_agent, details JSON)
     - `Ticker` (id, symbol unique, name, created_at) — master table per A1
     - `BrokerCredential` (id, user_id FK, broker, encrypted_refresh_token bytes, token_nonce bytes, token_tag bytes, expires_at, last_refreshed_at, timestamps) — supports Schwab OAuth storage from v1
   - `db/repositories/`: one repo file per entity (UserRepository, TickerRepository, etc.). All DB queries live here; API routes never write SQL directly (Clean Architecture per rule 3).
   - `alembic/` — A5: initial migration captures Phase 0 schema. `docker-entrypoint.sh` runs `alembic upgrade head` on startup.
   - `api/v1/auth_routes.py`: `POST /api/v1/login`, `POST /api/v1/refresh`, `POST /api/v1/logout`
     - Login issues fresh JWT every time (E2), sets httpOnly + SameSite=Lax cookie (B1, E4)
     - Error responses per B6 standardized envelope
     - IP-based rate limit + lockout (E5)
   - **API versioning**: ALL routes under `/api/v1/*` from day 1 (B5)
   - **Startup seeding**: on first boot, if `users` table empty, create admin from `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH` env vars; refuse to start if either missing

3. **Frontend scaffold (frontend-builder — in parallel)**
   - Vite + React + TypeScript + Tailwind setup
   - Login page (functional, connects to /api/login)
   - App shell with nav (Dashboard/Positions/History/Settings tabs)
   - Auth context + protected routes
   - Fetch wrapper with auto-refresh on 401

4. **Dependency management (per I8)**
   - Backend: `requirements.in` (top-level only) → `pip-compile` → `requirements.txt` (fully pinned)
   - `Makefile` targets: `deps-update` (regenerate requirements.txt + run pip audit), `deps-sync` (pip-sync to install pinned)
   - Frontend: `package-lock.json` committed (npm default behavior)

5. **Operational scripts (per I3, I21)**
   - `scripts/reset_password_offline.py`: runs on VM without app; connects directly to SQLite; prompts for new password; validates with zxcvbn; writes bcrypt hash
   - `scripts/set_password.py`: generates initial ADMIN_PASSWORD_HASH (used during setup)
   - `scripts/rotate_age_key.sh`: age key rotation procedure (documented, run manually)
   - `scripts/rotate_secrets.py`: rotates JWT_SECRET / ENCRYPTION_KEY (the latter requires re-encrypting BrokerCredential rows)
   - `scripts/setup_secrets.sh`: interactive first-time SOPS + age setup

6. **Healthcheck + graceful shutdown (per I23, I24)**
   - `api/v1/health_routes.py`: `GET /api/v1/health` → `{status, db, scheduler, data_sources}` structured response
   - Dockerfile: `HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/api/v1/health || exit 1`
   - FastAPI lifespan handler: shutdown calls `scheduler.shutdown(wait=True)` + closes DB engine
   - uvicorn: `--timeout-graceful-shutdown 30`

7. **NTP + timezone (per I22)**
   - Dockerfile: `apt-get install -y ntpdate` + `ENV TZ=UTC`
   - docker-entrypoint.sh: `ntpdate -s time.google.com || true` on startup
   - App code: explicit `zoneinfo.ZoneInfo("America/New_York")` for all market dates

8. **Run security-auditor on Phase 0 output**

**Estimated time: 1.5 days**
**Milestone: Can login to an empty dashboard via browser. Reset password script works. Healthcheck passes.**

---

### Phase 1: Data Layer (Day 2-3)
**Backend-builder handles all of this**

Tasks:
1. **DataSource interface**
   - `datasources/base.py`: Abstract class with methods:
     - `bulk_download(symbols: list[str], period: str) -> dict[str, DataFrame]` ← PREFER this over single-ticker loops
     - `get_daily_ohlcv(symbol, start, end) -> DataFrame` (convenience wrapper, internally uses bulk)
     - `get_index_data(symbol) -> DataFrame` (for SPX, VIX, DXY)
     - `health_check() -> bool`
   - `datasources/yfinance_source.py` — MUST follow these rules:
     - Use `yf.download(" ".join(symbols), period="2y", group_by="ticker", threads=False, progress=False, auto_adjust=True)` — ONE call for N tickers. Never loop per-ticker. `threads=False` to avoid Yahoo anti-abuse.
     - Wrap with tenacity: `@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=2, max=30))`
     - Cache raw response as parquet to `data/cache/yfinance/{YYYY-MM-DD}_{symbols_hash}.parquet` BEFORE parsing. On parse failure, subsequent retries hit cache, not network.
     - Split bulk DataFrame into per-ticker DataFrames at the interface boundary so indicators work per-ticker downstream.
   - `datasources/fred_source.py`: Yield spread, DXY, Fed Funds Rate (via fredapi, simpler — no bulk batch concern)

2. **SQLite models for market data**
   - `DailyPrice` (symbol, date, open, high, low, close, volume) — UNIQUE (symbol, date), UPSERT on insert for idempotency
   - `MacroIndicator` (name, date, value) — UNIQUE (name, date), UPSERT
   - `Watchlist` (symbol, added_date, data_status: enum "pending"|"ready"|"failed")

3. **Centralized data ingestion module** (`backend/app/ingestion/` — per I7)
   - `daily_ingestion.py`: Orchestrator for daily_update. Flow:
     1. Fetch ALL ticker OHLCV in ONE bulk call: `yf.download(" ".join(all_symbols), ...)`
     2. Fetch macro data (DXY, 10Y, 2Y, Fed Funds) from FRED in batched calls
     3. Persist raw data via UPSERT to DailyPrice, MacroIndicator
     4. Trigger indicator computation (indicator modules read from DB, never call network)
     5. Store DailySignal, MarketSnapshot
   - `backfill.py`: `backfill_ticker(symbol, years=2, data_source, db) -> None` — for cold-start single-ticker add
   - **Concurrency guard** (per I4):
     - Process-level `asyncio.Lock` dict keyed by symbol
     - Background backfill task checks `watchlist.data_status != "pending"` before starting
     - UNIQUE(user_id, symbol) on Watchlist → second POST returns 409
   - **Market calendar check** (per I6):
     - `pandas_market_calendars.get_calendar("NYSE")` used in daily_ingestion
     - If not a trading day: log and return (no data fetch, no computation)
     - Market holidays trigger "market closed today" in API response

4. **API routes — with cold-start handling**
   - `POST /api/watchlist` — add ticker with immediate backfill:
     ```python
     async with asyncio.timeout(5):
         await backfill_ticker(symbol, years=2, ...)
         await compute_indicators(symbol, ...)
         return WatchlistResponse(data_status="ready")
     except TimeoutError:
         background_tasks.add_task(backfill_then_compute, symbol)
         return WatchlistResponse(data_status="pending")
     ```
   - `GET /api/watchlist` — list current watchlist
   - `DELETE /api/watchlist/{symbol}` — remove
   - `GET /api/data/status` — data source health + per-ticker data_status
   - `POST /api/data/refresh` — manual trigger (rate-limited)
   - `GET /api/ticker/{symbol}?only_status=1` — light endpoint for frontend polling during pending backfill

5. **Historical data preload** (one-time seed)
   - Script: pull 2 years for default watchlist (SPY, QQQ, IWM) using bulk_download
   - Run on first startup if DailyPrice is empty

6. **Run test-writer**: DataSource tests with mocked yfinance responses, including failure/retry paths and cache hit paths
7. **Run security-auditor**

**Estimated time: 2 days**
**Milestone: Can add tickers to watchlist, backend fetches and stores price data, UI shows data immediately (or skeleton + polls for pending)**

---

### Phase 2: Indicators Engine (Day 4-6)
**Backend-builder — this is the core logic**

Tasks (can parallelize indicator groups):

1. **Indicator base class (per I7 — pure functions, no network calls)**
   - `indicators/base.py`: Abstract with `calculate(df: DataFrame, context: IndicatorContext) -> IndicatorResult`
   - Indicators receive pre-fetched DataFrames and ONLY read DB via the context (read-only repo)
   - `IndicatorResult` (frozen Pydantic model):
     - `value: float` — raw number
     - `signal: SignalTone` — GREEN | YELLOW | RED
     - `data_sufficient: bool` — false when insufficient history (e.g., ticker <200 days for 200MA)
     - `short_label: str` — for pros/cons UI (e.g., "MACD 金叉")
     - `detail: dict` — expandable raw data (e.g., `{macd_line: 0.43, signal_line: 0.21, histogram: 0.22}`)
     - `computed_at: datetime`
   - `indicator_version: str` (semver) — across all indicators, bumps when formula changes

2. **Market regime indicators (4)**
   - `spx_ma.py`: SPX 50/200 MA position + golden/death cross detection
   - `ad_day.py`: Accumulation/Distribution Day count (25-day window)
   - `vix.py`: VIX level + 10-day trend direction
   - `yield_spread.py`: 10Y-2Y from FRED, inversion detection

3. **Per-ticker indicators (4)**
   - `price_vs_ma.py`: Price vs 50MA and 200MA
   - `rsi.py`: RSI(14) daily + RSI(14) weekly
   - `volume_anomaly.py`: Volume vs 20-day average, spike detection (>2x)
   - `relative_strength.py`: Ticker return vs SPX return (20-day rolling)

4. **Timing indicators (2)**
   - `macd.py`: MACD line, signal line, histogram, crossover detection
   - `bollinger.py`: 20MA ± 2σ, position within bands

5. **Macro indicators (2)**
   - `dxy.py`: DXY trend (20-day MA direction)
   - `fed_rate.py`: Current rate from FRED + narrative

6. **Run test-writer**: Each indicator tested with known data (e.g., RSI of a known sequence should equal a known value)
7. **Run security-auditor**

**Estimated time: 3 days**
**Milestone: Can compute all 12 indicators for any ticker**

---

### Phase 3: Signal Rules + Recommendations (Day 7-8)
**Backend-builder**

Tasks:
1. **Voting system — two independent decision layers (per I1 in STAFF_REVIEW_DECISIONS.md)**
   - `signals/market_posture.py`: Layer 1 — 4 market-regime indicators vote → 進攻/正常/防守 enum
   - `signals/direction.py`: Layer D1a — 4 direction indicators vote → ActionCategory (強力買入 / 買入 / 持有 / 觀望 / 減倉 / 出場)
   - `signals/timing.py`: Layer D1b — 2 timing indicators (MACD, BB) → TimingModifier enum (favorable / mixed / unfavorable)
   - `signals/compose.py`: `compose_ticker_signal(direction_action, timing_modifier) -> Signal` — applies rules:
     - Timing modifier only appears for 強力買入/買入/持有 actions (buy-side)
     - 觀望/減倉/出場 suppresses timing badge (not relevant when exiting)
     - All-NEUTRAL (data_sufficient=False for all 4 direction) → 觀望 + "資料不足以判斷" note
   - ALL classifications via pure-function decision tables, NOT if/elif chains:
     ```python
     DIRECTION_TABLE = [
         # (min_green, max_green, min_red, max_red, action)
         (4, 4, 0, 0, ActionCategory.STRONG_BUY),
         (3, 3, 0, 1, ActionCategory.BUY),
         (2, 2, 0, 1, ActionCategory.HOLD),
         ...
     ]
     def classify_direction(greens: int, reds: int) -> ActionCategory:
         for min_g, max_g, min_r, max_r, action in DIRECTION_TABLE:
             if min_g <= greens <= max_g and min_r <= reds <= max_r:
                 return action
         return ActionCategory.NEUTRAL  # fallback
     ```

2. **Entry price calculator — timing-aware emphasis**
   - `signals/entry_price.py`: 3 tiers (50MA / BB mid / 200MA) + split suggestion 30/40/30
   - Emphasis depends on timing modifier:
     - `favorable` → 積極進場 highlighted
     - `mixed` → all equal
     - `unfavorable` → 理想/保守 highlighted, 積極 dimmed

3. **Stop-loss calculator**
   - `signals/stop_loss.py`: Dynamic based on trend health (see STAFF_REVIEW_DECISIONS.md I1)
   - Healthy trend: 200MA - 3%
   - Weakening trend: Bollinger lower band - 3%

4. **Pros/Cons structured output** (per no-template-narrator rule)
   - `signals/pros_cons.py`: Converts each indicator result into `ProsConsItem{category, tone, short_label, detail}`
   - `category`: "direction" | "timing" | "macro" | "risk"
   - `tone`: "pro" | "con" | "neutral"
   - API response includes `pros_cons: ProsConsItem[]` alongside raw indicator data
   - Frontend renders as scannable list (no prose generation)
   - If LLM narrative ever needed: `signals/llm_narrator.py` POSTs JSON to Claude Haiku with strict prompt. v2+.

5. **API routes (all under /api/v1/)**
   - GET `/api/v1/market-posture`: Market regime summary (4 indicators + overall posture + streak days)
   - GET `/api/v1/ticker/{symbol}`: Full indicator data + signal (action + timing modifier) + entry/stop prices + `pros_cons: []` array
   - GET `/api/v1/ticker/{symbol}/history?limit=30`: Historical signals with pagination wrapper `{data, total, has_more}`

6. **Daily snapshot storage**
   - `DailySignal` model: UNIQUE(symbol, date), UPSERT (INSERT...ON CONFLICT DO UPDATE). Fields: date, symbol, action (enum), timing_modifier (enum), direction_green_count, direction_red_count, entry_aggressive, entry_ideal, entry_conservative, stop_loss, computed_at, indicator_version
   - `MarketSnapshot` model: UNIQUE(date), UPSERT. Fields: date, posture, 4 regime indicator values, computed_at, indicator_version
   - `MarketPostureStreak` model: tracks consecutive days of same posture

7. **Run test-writer**: Voting logic with all edge cases (all green, all red, mixed, etc.)
8. **Run security-auditor**

**Estimated time: 2 days**
**Milestone: API returns full analysis for any ticker with Chinese narrative**

---

### Phase 4: Frontend — Dashboard + Ticker Detail (Day 9-12)
**Frontend-builder — the big UI phase**

Tasks:
1. **Dashboard page**
   - Market posture card (4 indicators with 🟢🟡🔴)
   - "Needs attention" alert section (filtered: only 減倉/出場/強力買入)
   - Watchlist table (sortable, clickable rows)
   - Positions summary card (total P&L)
   - Macro backdrop card
   - Mobile responsive layout

2. **Ticker Detail page**
   - Action badge header: composed from direction + timing layers (per STAFF_REVIEW_DECISIONS.md I1)
     - Main: `強力買入 🟢🟢` / `買入 🟢` / `持有 ✓` / `觀望 👀` / `減倉 ⚠️` / `出場 🔴🔴`
     - Timing modifier (buy-side only): `✓ 時機好` / `⏳ 等回調` / (none)
     - Examples: `強力買入 🟢🟢 ⏳ 等回調` (方向對但現在追高) / `持有 ✓`
   - TradingView Lightweight Charts integration:
     - Candlestick series + volume histogram
     - 50MA / 200MA line overlays
     - Bollinger Bands overlay
     - Time range selector (1M/3M/6M/1Y/ALL)
     - Mobile optimization (per F3): default only K-line + 200MA; "顯示進階指標" toggle adds BB + 50MA + volume
   - **Pros/Cons summary card**:
     - Two columns: 🟢 Pros | 🔴 Cons (separated by category: Direction / Timing / Macro)
     - Each row: indicator short label + tap to expand for raw numbers
     - Example rows: `🟢 MACD 金叉` / `🔴 VIX 上升` / `🟢 價格在 200MA 上方`
     - Neutral + insufficient data collapsed under "⚪ Neutral signals (N)" expandable row
   - Direction indicators card (4 items, detailed view with expand)
   - Timing indicators card (2 items, detailed view)
   - Entry price section with visual progress bars + timing-aware emphasis (per STAFF_REVIEW_DECISIONS.md I1)
   - Stop-loss display
   - Split suggestion (30/40/30, "僅供參考" label)
   - Delisted/invalid badge handling (per I18): grey out + "🚫 Delisted" if `data_status=delisted`
   - Signal history table (last 30 days)

3. **Shared components (per I20 accessibility + I17 validation)**
   - `SignalBadge` — emoji + Chinese text label + letter redundancy for color-blind (🟢 買 / 🟡 持 / 🔴 賣). ARIA label on every instance.
   - `ActionBadge` — 6 action categories (強力買入 🟢🟢, 買入 🟢, 持有 ✓, 觀望 👀, 減倉 ⚠️, 出場 🔴🔴)
   - `TimingModifier` — optional badge (✓ 時機好 / ⏳ 等回調) rendered after ActionBadge
   - `PriceBar` — visual distance to entry/stop prices with aria-valuenow
   - `ProsConsCard` — dual-column list, expand-to-detail, grouped by category
   - `TickerInput` — validated input with regex `^[A-Z0-9.\-]{1,10}$`, auto-uppercase on paste
   - `MarketClosedBanner` — shown when `is_market_open=false` (per I6)
   - `StopLossTriggeredBanner` — red banner for triggered positions
   - `EmailBatchModeBanner` — quota warning banner (per I5)
   - `DelistedBadge` — for tickers with `data_status=delisted`
   - `NavBar` (responsive, mobile hamburger)
   - `LoadingSpinner`

4. **Run security-auditor**

**Estimated time: 4 days**
**Milestone: Can browse dashboard, click into any ticker, see full analysis with charts**

---

### Phase 5: Frontend — Positions + History + Settings (Day 13-15)
**Frontend-builder**

Tasks:
1. **Positions page (per A4 + I1)**
   - Position list with P&L per position
   - Add/edit/delete position forms
   - "Record buy/sell" action (appends to Trade table; Position.shares derived)
   - **Corporate action warning banner** (per I1): "Corporate actions (splits, dividends) are NOT automatically adjusted. Recheck your avg_cost after any split. See [ticker] for split history."
   - Pie chart (allocation visualization — use Recharts)
   - Trade history log (append-only per A4)
   - Stop-loss reset button (clears `stop_loss_triggered_at` per I9)

2. **Positions API (backend-builder in parallel)**
   - `db/models.py`: Position (never deleted, soft by shares=0), Trade (append-only)
   - CRUD `/api/v1/positions`
   - POST `/api/v1/positions/{id}/add`, `/api/v1/positions/{id}/reduce`
   - POST `/api/v1/positions/{id}/reset-stop-loss-alert`
   - Validation: reduce cannot result in negative shares (400 Bad Request)
   - Trade log auto-generated on add/reduce
   - FK: all tables have `user_id` FK per A3

3. **History page**
   - Market posture timeline chart with streak visualization
   - Signal accuracy table (calculated from stored DailySignal vs actual future price movement — computed on-demand or via nightly job)
   - "My decisions vs Eiswein" comparison (joins Trade + DailySignal tables)
   - Pattern matching section (cosine similarity on 12-indicator vectors)

4. **History API (backend-builder in parallel)**
   - GET `/api/v1/history/accuracy?days=90`
   - GET `/api/v1/history/decisions`
   - GET `/api/v1/history/patterns?top_n=5`
   - All use pagination wrapper `{data, total, has_more}` per B4

5. **Settings page (per I14 + I10 + I20 + E1)**
   - Watchlist management (search + add/remove, with TickerInput validation per I17)
   - **Broker connections section** (per I14):
     - Schwab status: 🟢 connected (5d 12h left) / 🟡 <2 days / 🔴 expired
     - "重新連接 Schwab" button → OAuth flow
     - Button to disconnect
   - Data source status display (yfinance / FRED / Schwab health per I23)
   - Email notification preferences + current quota status
   - Password change form (validates new password via zxcvbn per E1)
   - Login audit log display
   - System info (DB size, last update, last backup, last vacuum)
   - Manual data refresh button (rate-limited)
   - Backup download
   - **Footer disclaimer (per I10)**: "Data sourced from Yahoo Finance (yfinance library). See https://finance.yahoo.com/terms"
   - **Disclaimer (per J)**: "此工具僅為個人決策輔助，不構成投資建議。使用者自行承擔所有交易決策風險。"

6. **Schwab OAuth callback (backend-builder)**
   - `GET /api/v1/broker/schwab/callback?code=...&state=...`
   - Exchange authorization code for access + refresh tokens
   - AES-256-GCM encrypt refresh token → store in BrokerCredential table
   - Redirect to Settings page with success/error status

7. **Run test-writer**: Frontend component tests, API integration tests
8. **Run security-auditor**: Full audit of all pages and endpoints, especially OAuth callback

**Estimated time: 3 days**
**Milestone: All 6 pages functional**

---

### Phase 6: Cron Jobs + Email (Day 16-17)
**Backend-builder**

Tasks:
1. **Daily update job** (`jobs/daily_update.py`)
   - Pull latest data for all watchlist tickers
   - Compute all 12 indicators
   - Generate signals + entry/stop prices
   - Store DailySignal + MarketSnapshot in SQLite
   - Send email summary (use `smtplib` + Gmail app password or SendGrid free tier)

2. **Backup job** (`jobs/backup.py`)
   - `sqlite3 .backup` to data/backups/
   - Rotate: keep last 30 daily backups

3. **Token reminder job** (`jobs/token_reminder.py`)
   - Check Schwab token expiry date
   - Send email if < 2 days remaining

4. **Email template**
   - HTML email with market posture + attention items + top movers
   - Plain text fallback

5. **Scheduler setup** — `jobs/scheduler.py` with file lock protection
   - Use `AsyncIOScheduler` from APScheduler, started from FastAPI lifespan hook
   - **MUST acquire fcntl.flock on `/tmp/eiswein-scheduler.lock` BEFORE starting** — if lock already held, skip (defensive against future workers>1 misconfiguration)
   - Keep file descriptor open for lifetime of process (so lock persists)
   - Jobs:
     - Daily update: `CronTrigger(hour=6, minute=30, timezone="America/New_York")` — after US close + Asian market open
     - Backup: `CronTrigger(hour=7, minute=0, timezone="America/New_York")`
     - Token expiry check: `CronTrigger(hour=12, minute=0)` — daily
     - **Intra-day stop-loss check (D4)**: `IntervalTrigger(minutes=30)` during US market hours (`CronTrigger(day_of_week='mon-fri', hour='9-16', timezone="America/New_York")`)
       - For each Position with an active stop-loss, fetch current price (delayed quote via yfinance OK)
       - If price ≤ stop-loss → mark `stop_loss_triggered_at`, escalate signal to 出場, send immediate email alert
       - Idempotent: only fire alert once per position per trigger event
     - Email outbox retry (H3): `IntervalTrigger(hours=1)`
   - Every job wrapped in try/except + structured logging so one failure doesn't crash the scheduler
   - Daily update: iterate watchlist, PER-TICKER try/except — one failing ticker doesn't abort the whole job (graceful degradation)

6. **Email outbox with quota tracking (H3 + I5)**
   - New table `EmailOutbox` (id, to_address, subject, html_body, text_body, category, status enum {pending, sent, failed, batched}, attempt_count, last_attempted_at, sent_at, created_at)
   - New table `EmailQuota` (date, sent_count, batch_mode_enabled) — daily quota tracking
   - All emails written via `email_outbox_repo.enqueue()` rather than sent synchronously
   - `jobs/email_dispatcher.py`:
     - Pulls pending → SMTP send → update status
     - Checks EmailQuota daily count. If count >= 400 (80% of 500 Gmail limit) → flip batch_mode_enabled=true
     - In batch mode: pending emails marked `status=batched`; hourly job aggregates all batched events into ONE summary email
     - Batch mode resets at midnight ET (new quota day)
   - Max 5 retries with exponential backoff
   - >24h in failed → audit_log entry + in-app banner on next dashboard load
   - In-app banner when batch mode active: "⚠️ 每日 email 配額接近上限，目前使用摘要模式"

7. **Intra-day stop-loss — dedup protection (per I9)**
   - Position model gains `stop_loss_triggered_at: datetime | None`
   - Job logic:
     ```python
     if position.current_price <= position.stop_loss:
         today = now_et.date()
         triggered_today = (position.stop_loss_triggered_at 
                            and position.stop_loss_triggered_at.date() == today)
         if not triggered_today:
             await send_stop_loss_alert(position)
             position.stop_loss_triggered_at = now_et
     ```
   - Settings: "Reset stop-loss alerts" button clears all `stop_loss_triggered_at` (for manual reset)
   - Job only runs on trading days (market calendar check)

8. **SQLite VACUUM job (per I15)**
   - `jobs/vacuum.py`: weekly Sunday 03:00 ET
   - `PRAGMA incremental_vacuum` (non-blocking)
   - Optional: full VACUUM if `PRAGMA freelist_count > threshold`

9. **Parquet cache eviction (per I16)**
   - Daily cleanup step in backup job: `find data/cache/yfinance -mtime +7 -delete`

**Estimated time: 2.5 days**
**Milestone: Receive daily email report, data auto-updates, intra-day stop-loss alerts work, duplicate scheduler protection verified**

---

### Phase 7: Docker + Deployment (Day 18-19)
**Backend-builder (orchestrator may help with infra)**

Tasks:
1. **Dockerfile** (multi-stage)
   - Stage 1: Node → build React
   - Stage 2: Python 3.12-slim → install deps, copy backend + React build
   - FastAPI serves static files + API
   - ARM-compatible (for Oracle Cloud)

2. **docker-compose.yml**
   - Single service with volume mounts (data/, .env)
   - Health check endpoint
   - **MUST pin uvicorn to single worker**:
     ```yaml
     command: [
       "uvicorn", "backend.app.main:app",
       "--host", "0.0.0.0",
       "--port", "8000",
       "--workers", "1",          # NEVER raise this. APScheduler safety + SQLite single-writer.
       "--loop", "uvloop",
       "--proxy-headers"
     ]
     ```
   - Document this invariant inline with a comment — the file lock guard in `jobs/scheduler.py` is belt-and-suspenders for this constraint.

3. **SOPS + age secret management (G4 — NO PLAINTEXT SECRETS)**
   - Install SOPS and age binaries in Dockerfile (~5MB overhead)
   - Repo structure:
     - `secrets/eiswein.enc.yaml` — SOPS-encrypted env vars (committed)
     - `secrets/eiswein.enc.yaml.template` — unencrypted template showing structure
     - `scripts/setup_secrets.sh` — interactive onboarding (age-keygen, sops edit)
     - `scripts/rotate_age_key.sh` — key rotation procedure
   - VM setup:
     - `age.key` at `/etc/eiswein/age.key` (chmod 600, owned by root)
     - Backed up to user's 1Password
   - docker-entrypoint.sh decryption flow:
     ```bash
     #!/bin/bash
     set -euo pipefail
     export SOPS_AGE_KEY_FILE=/etc/eiswein/age.key
     eval "$(sops -d /app/secrets/eiswein.enc.yaml | grep -v '^#' | xargs -I {} echo 'export {}')"
     exec "$@"
     ```
     - Decrypted secrets only exist in process environment (never written to disk)
     - `/tmp` mounted as tmpfs so any incidental temp files never hit disk
   - CI/CD:
     - GitHub Actions repository secret `AGE_KEY` contains the age private key (already encrypted at rest by GitHub)
     - Build step writes it to a runner-local file for SOPS to use if testing encrypted configs
     - Age key is NOT included in published Docker image
   - Boot volume encryption enabled on VM (Oracle Cloud / Hetzner both offer this)
   - Document the full threat model + rotation procedure in `docs/SECURITY.md`

4. **Cloudflare Named Tunnel (G1)**
   - Use Named Tunnel (not Legacy) — managed via Cloudflare dashboard
   - `cloudflared` runs as sidecar container in docker-compose
   - Tunnel config (`tunnel.yml`) references the tunnel UUID + routes eiswein.yourdomain.com → eiswein:8000
   - VM firewall: inbound ALL BLOCKED except SSH (22) from your IP. No public 80/443.

5. **Cloudflare Access (E3, first auth layer)**
   - Set up Access Application for eiswein.yourdomain.com
   - Policy: allow your Google account only
   - App JWT verifies CF Access JWT header as belt-and-suspenders (CF-signed, verify against CF's public keys)

6. **GitHub Actions CI/CD (G3)**
   - `.github/workflows/deploy.yml`:
     - On push to main: run tests, security audit, lint
     - Build multi-arch Docker image (linux/amd64 + linux/arm64 for Oracle ARM)
     - Push to `ghcr.io/ayou7995/eiswein:latest`
   - VM runs `watchtower` container watching for new image tags, auto-pulls and restarts
   - No manual SSH needed for deploys

7. **Image size target <300MB (G2)**
   - `.dockerignore`: tests/, node_modules/, data/cache/, .venv/, **/__pycache__
   - `pip install --no-cache-dir`
   - Multi-stage: build deps discarded from final image
   - `python:3.12-slim-bookworm` base

8. **Run security-auditor**: Final full audit

9. **Manual first deploy**
   - Test docker-compose up locally first
   - Configure VM (install Docker, cloudflared, age.key)
   - Initial deploy via SSH (subsequent deploys automated by Watchtower)
   - Verify: login works, dashboard loads on phone via https, no plaintext secrets anywhere

**Estimated time: 2 days**
**Milestone: Live on cloud, accessible via HTTPS from phone**

---

## Timeline Summary

| Phase | Days | What | Milestone |
|-------|------|------|-----------|
| 0 | 2 | Scaffold + Security + Alembic + User + Healthcheck + NTP + ops scripts | Login works, DB migrations in place, password-reset script works |
| 1 | 2.5 | Data Layer + Centralized Ingestion + Schwab OAuth stub + Market calendar | Watchlist works, ONE bulk yfinance call, Schwab connect UI |
| 2 | 3 | 12 Indicators (pure functions) | All 12 indicators compute + pandas_ta validation via fixture snapshots |
| 3 | 2 | Signals (Direction + Timing layers) + Pros/Cons + Entry/Stop | Full analysis API with two-layer decision tables |
| 4 | 4 | Dashboard + Ticker UI + Mobile optimization + A11y | Browse + charts on mobile + color-blind support |
| 5 | 3 | Positions (Trade append-only) + History + Settings + Schwab OAuth UI + CA warning | All pages + manual broker re-auth flow + corporate actions banner |
| 6 | 3 | Cron + EmailOutbox quota + Intra-day stop-loss dedup + VACUUM | Daily report + stop-loss alerts + quota batch mode |
| 7 | 2.5 | Docker + SOPS + CF Tunnel + GitHub Actions CI/CD + Watchtower | Live on cloud, encrypted secrets, auto-deploy pipeline |
| **Total** | **~22 working days** | | |

With multi-agent parallelization (backend + frontend in Phase 4-5), actual calendar time ~16-17 days.

## Parallelization Opportunities

```
Phase 0:  [backend-builder: security] ←→ [frontend-builder: scaffold]
Phase 1:  [backend-builder: data layer] → [test-writer: data tests]
Phase 2:  [backend-builder: indicators] → [test-writer: indicator tests]
Phase 3:  [backend-builder: signals] → [test-writer: signal tests]
Phase 4:  [frontend-builder: dashboard+ticker] ←→ [backend-builder: API polish]
Phase 5:  [frontend-builder: positions+history] ←→ [backend-builder: history API]
Phase 6:  [backend-builder: cron+email]
Phase 7:  [backend-builder: docker+deploy]

Security-auditor runs at end of EVERY phase.
```

## Verification Plan

After each phase:
1. Run `pytest` (backend tests)
2. Run `npm test` (frontend tests)  
3. Run `@security-auditor` on changed files
4. Manual smoke test in browser (start dev servers)
5. `pip audit` + `npm audit` for dependency vulnerabilities

Final verification:
1. Docker build + run locally
2. Login flow (password → JWT → protected routes)
3. Add tickers to watchlist → see data populate
4. Click into ticker → verify all 12 indicators + chart + narrative
5. Add positions → verify P&L calculations
6. Trigger manual data refresh → verify update
7. Check mobile layout on phone
8. Run security-auditor on entire codebase
9. Deploy to cloud VM → verify Cloudflare Tunnel + Access
