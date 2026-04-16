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

### Phase 0: Project Scaffold + Security Foundation (Day 1)
**Priority: CRITICAL — everything depends on this**

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
   - `config.py`: Pydantic Settings reading from env vars (JWT_SECRET, ENCRYPTION_KEY, FRED_API_KEY, etc.)
   - `security/auth.py`: JWT create/verify, bcrypt hash/verify, login attempt throttling
   - `security/encryption.py`: AES-256 encrypt/decrypt for Schwab tokens
   - `security/rate_limit.py`: slowapi setup
   - `security/middleware.py`: Security headers (CSP, HSTS, X-Frame-Options), request logging
   - `db/database.py`: SQLite engine + session factory
   - `db/models.py`: User, AuditLog tables
   - `api/auth_routes.py`: POST /login, /refresh, /logout

3. **Frontend scaffold (frontend-builder — in parallel)**
   - Vite + React + TypeScript + Tailwind setup
   - Login page (functional, connects to /api/login)
   - App shell with nav (Dashboard/Positions/History/Settings tabs)
   - Auth context + protected routes
   - Fetch wrapper with auto-refresh on 401

4. **Run security-auditor on Phase 0 output**

**Estimated time: 1 day**
**Milestone: Can login to an empty dashboard via browser**

---

### Phase 1: Data Layer (Day 2-3)
**Backend-builder handles all of this**

Tasks:
1. **DataSource interface**
   - `datasources/base.py`: Abstract class with methods:
     - `get_daily_ohlcv(symbol, start, end) -> DataFrame`
     - `get_index_data(symbol) -> DataFrame` (for SPX, VIX, DXY)
     - `health_check() -> bool`
   - `datasources/yfinance_source.py`: Implementation
   - `datasources/fred_source.py`: Yield spread, DXY, Fed Funds Rate

2. **SQLite models for market data**
   - `DailyPrice` (symbol, date, open, high, low, close, volume)
   - `MacroIndicator` (name, date, value)
   - `Watchlist` (symbol, added_date)

3. **API routes**
   - CRUD `/api/watchlist`
   - GET `/api/data/status` (data source health)
   - POST `/api/data/refresh` (manual trigger)

4. **Historical data preload job**
   - Pull 2 years of daily data for a default watchlist (SPY, QQQ, IWM + a few stocks)
   - Store in SQLite

5. **Run test-writer**: DataSource tests with mocked yfinance responses
6. **Run security-auditor**

**Estimated time: 2 days**
**Milestone: Can add tickers to watchlist, backend fetches and stores price data**

---

### Phase 2: Indicators Engine (Day 4-6)
**Backend-builder — this is the core logic**

Tasks (can parallelize indicator groups):

1. **Indicator base class**
   - `indicators/base.py`: Abstract with `calculate(df: DataFrame) -> IndicatorResult`
   - `IndicatorResult`: value, signal (GREEN/YELLOW/RED), explanation_zh (白話文)

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
1. **Voting system**
   - `signals/voting.py`: Market posture (4 votes → 進攻/正常/防守)
   - `signals/voting.py`: Per-ticker action (6 votes → 6 categories)

2. **Entry price calculator**
   - `signals/entry_price.py`: 3 tiers (50MA / BB mid / 200MA) + split suggestion

3. **Stop-loss calculator**
   - `signals/stop_loss.py`: Dynamic based on trend health

4. **Narrator (白話文 generator)**
   - `signals/narrator.py`: Takes all indicator results + signal → produces Chinese plain-language explanation
   - Template-based for v1 (not LLM-generated)

5. **API routes**
   - GET `/api/market-posture`: Market regime summary
   - GET `/api/ticker/{symbol}`: Full indicator + signal + entry/stop/narrative
   - GET `/api/ticker/{symbol}/history`: Historical signals

6. **Daily snapshot storage**
   - `DailySignal` model: date, symbol, all indicator values, action, entry prices, stop-loss
   - `MarketSnapshot` model: date, posture, 4 regime indicator values

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
   - TradingView Lightweight Charts integration:
     - Candlestick series + volume histogram
     - 50MA / 200MA line overlays
     - Bollinger Bands overlay
     - Time range selector (1M/3M/6M/1Y/ALL)
   - Direction indicators card (4 items with 🟢🟡🔴)
   - Timing indicators card (2 items)
   - Entry price section with visual progress bars
   - Stop-loss display
   - Split suggestion (僅供參考)
   - Plain-language narrative section (白話解讀)
   - Signal history table (last 30 days)

3. **Shared components**
   - `SignalBadge` (🟢🟡🔴 with label)
   - `ActionBadge` (6 categories with icons)
   - `PriceBar` (visual distance to entry/stop prices)
   - `NavBar` (responsive, mobile hamburger)
   - `LoadingSpinner`

4. **Run security-auditor**

**Estimated time: 4 days**
**Milestone: Can browse dashboard, click into any ticker, see full analysis with charts**

---

### Phase 5: Frontend — Positions + History + Settings (Day 13-15)
**Frontend-builder**

Tasks:
1. **Positions page**
   - Position list with P&L per position
   - Add/edit/delete position forms
   - "Record buy/sell" action (auto-recalculates avg cost)
   - Pie chart (allocation visualization — use Recharts for this one)
   - Trade history log

2. **Positions API (backend-builder in parallel)**
   - `db/models.py`: Position, Trade tables
   - CRUD `/api/positions`
   - POST `/api/positions/{id}/add`, `/api/positions/{id}/reduce`
   - Trade log auto-generated on add/reduce

3. **History page**
   - Market posture timeline chart
   - Signal accuracy table (calculated from stored DailySignal vs actual price movement)
   - "My decisions vs Eiswein" comparison (joins Trade + DailySignal tables)
   - Pattern matching section (cosine similarity on 12-indicator vectors)

4. **History API (backend-builder in parallel)**
   - GET `/api/history/accuracy`
   - GET `/api/history/decisions`
   - GET `/api/history/patterns`

5. **Settings page**
   - Watchlist management (search + add/remove)
   - Data source status display
   - Email notification preferences
   - Password change form
   - Login audit log display
   - System info (DB size, last update, last backup)
   - Manual data refresh button
   - Backup download

6. **Run test-writer**: Frontend component tests, API integration tests
7. **Run security-auditor**: Full audit of all pages and endpoints

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

5. **Scheduler setup**
   - APScheduler or cron in Docker entrypoint
   - Daily update: 06:30 EST (after US market close + Asian market context)
   - Backup: 07:00 EST
   - Token check: daily

**Estimated time: 2 days**
**Milestone: Receive daily email report, data auto-updates**

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

3. **.env.example** with all required vars documented

4. **Cloudflare Tunnel setup documentation**
   - `cloudflared` in Docker Compose as sidecar
   - Tunnel config for eiswein.yourdomain.com

5. **Cloudflare Access setup documentation**
   - OAuth with Google

6. **Run security-auditor**: Final full audit

7. **Deploy to VM**
   - Test on local Docker first
   - Push to VM, run docker-compose up

**Estimated time: 2 days**
**Milestone: Live on cloud, accessible via HTTPS from phone**

---

## Timeline Summary

| Phase | Days | What | Milestone |
|-------|------|------|-----------|
| 0 | 1 | Scaffold + Security | Login works |
| 1 | 2 | Data Layer | Watchlist + price data |
| 2 | 3 | Indicators | 12 indicators compute |
| 3 | 2 | Signals + Narrative | Full analysis API |
| 4 | 4 | Dashboard + Ticker UI | Browse + charts |
| 5 | 3 | Positions + History + Settings | All pages |
| 6 | 2 | Cron + Email | Daily auto-report |
| 7 | 2 | Docker + Deploy | Live on cloud |
| **Total** | **~19 working days** | | |

With multi-agent parallelization (backend + frontend in Phase 4-5), actual calendar time could be **~14-15 days**.

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
