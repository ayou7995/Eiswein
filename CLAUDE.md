# Eiswein — Personal Stock Market Decision-Support Tool

## Project Overview
A web dashboard that analyzes a user-managed watchlist using 12 technical indicators, produces daily signal reports (entry/exit/stop-loss recommendations), and tracks positions and decision history. Inspired by Heaton's Sherry trading system.

**Positioning**: Systematic decision-support / quantamental advisory (NOT automated quant trading). Human makes all final trading decisions.

## Architecture
- **Backend**: FastAPI (Python 3.12) + SQLite + SQLAlchemy
- **Frontend**: React + TypeScript + Tailwind CSS + TradingView Lightweight Charts
- **Deployment**: Single Docker container (multi-stage build: React → FastAPI serves static)
- **Cloud**: Oracle Cloud Free Tier (ARM, 24GB RAM) or Hetzner CX22 backup
- **Network**: Cloudflare Tunnel (no public ports) + Cloudflare Access (OAuth)

## Directory Structure
```
backend/app/
├── api/          # FastAPI routes under /api/v1/* (one file per resource)
├── db/           # SQLAlchemy models + session + Alembic migrations
├── datasources/  # Abstract DataSource + yfinance/FRED (Schwab/Polygon as stubs)
├── ingestion/    # Centralized orchestrator (bulk fetch, persist, then indicators compute from DB)
├── indicators/   # 12 indicator modules — PURE functions, no network calls
├── signals/      # direction.py + timing.py + compose.py + entry_price.py + stop_loss.py + pros_cons.py
├── security/     # Auth, encryption, rate limit, middleware, log_sanitizer
├── jobs/         # APScheduler + fcntl.flock: daily_update, intra_day_stop_loss, backup, vacuum, email_dispatcher
└── utils/        # Shared utilities

frontend/src/
├── pages/        # Route-level components (Dashboard, TickerDetail, ...)
├── components/   # Reusable UI (SignalBadge, PriceBar, ...)
├── api/          # Fetch wrapper + typed client
├── hooks/        # Shared React hooks
└── lib/          # Utilities, Zod schemas, constants
```

## Security Requirements (#1 PRIORITY)
- Cloudflare Tunnel + Cloudflare Access (first auth layer)
- App-level JWT (httpOnly cookie, SameSite=Lax, Secure) — second auth layer
- ALL secrets via SOPS + age encryption. NEVER plaintext on disk.
- Schwab refresh tokens: AES-256-GCM column-level encryption in BrokerCredential table
- Rate limiting (slowapi) keyed by CF-Connecting-IP; CSP/HSTS/X-Frame-Options headers; parameterized SQL only
- bcrypt (12 rounds) for password hashing; zxcvbn for strength validation
- Login throttling: IP-based 5 fails → 15 min lock; global 20 fails/min → email alert; all attempts audited
- Log sanitizer redacts password/token/secret/key from structlog output

## Sub-Agent Workflow
Delegate to specialized agents:
- `backend-builder` — FastAPI, indicators, data sources, signals, DB
- `frontend-builder` — React pages, Tailwind, charts
- `security-auditor` — Read-only security review (run after EVERY phase)
- `test-writer` — Unit + integration tests

After completing a module: run `security-auditor` then `test-writer`.

## Definition of Done (ALL 20 Rules Must Be Satisfied)

### Code Quality
1. **Zero-Lint & Type Compliance** — No `any`, no `@ts-ignore`, no linter bypasses. Python: mypy strict. TS: strict mode.
2. **Mandatory Test Coverage** — Every logic change needs unit tests (successes + failures).
3. **Strict Modular Boundaries** — Clean Architecture: logic separated from infrastructure.
4. **Standardized Error Handling** — Custom exception classes. No silent failures, no empty `catch`.
5. **Secure-by-Default** — Sanitize all inputs, no hardcoded secrets, env vars for all configs.

### Maintainability
6. **Self-Documenting Code** — Reads like prose. Comments explain "Why," never "What."
7. **DRY via Composition** — Shared logic in utilities. Refactor duplicates immediately.
8. **API Contract Stability** — Pydantic/Zod schemas defined first. Backward-compatible changes.
9. **Predictable Naming** — Domain-specific. Python: snake_case. TS: camelCase. Components: PascalCase.
10. **Performance Awareness** — No N+1 queries, no unnecessary re-renders, no memory leaks.

### Robustness
11. **Immutability First** — Prefer immutable data structures. Pure functions by default.
12. **Idempotency** — Actions safe to repeat without side effects.
13. **Dependency Injection** — Pass DB/logger/API clients as parameters. No global state.
14. **Graceful Degradation** — Loading/error states for every UI piece. Backend survives sub-service failures.
15. **Logging & Observability** — Structured logs with context (IDs, timestamps). No PII.

### Operability
16. **Environment Agnosticism** — Works identically across local/staging/prod via config files.
17. **Atomic Commits/Changes** — Smallest logical units. No mixing refactors with features.
18. **Schema Validation** — Pydantic (backend) + Zod (frontend) at ALL boundaries.
19. **Accessibility & UX** — Semantic HTML, ARIA labels, meaningful HTTP status codes.
20. **Documentation Maintenance** — Update README.md when architecture/deps change.

## Code Conventions
- Python: type hints (mypy strict), Pydantic models, async where beneficial
- TypeScript: strict mode, no `any`, Zod for runtime validation
- No comments except non-obvious "why" explanations
- English for code identifiers, Traditional Chinese for user-facing text/labels

## Core Indicators (12)
**Market regime (4)**: SPX 50/200 MA, A/D Day Count, VIX level+trend, 10Y-2Y yield spread
**Per-ticker direction (4)**: Price vs 50/200 MA, RSI(14)+weekly RSI, volume anomaly, relative strength vs SPX
**Timing (2)**: MACD, Bollinger Bands
**Macro (2)**: DXY trend, Fed Funds Rate + market expectations

## Signal Rules (revised 2026-04-17)
- **Layer 1 (Market Posture)**: 4 market-regime indicators vote → 進攻/正常/防守
- **Layer D1a (Direction)**: 4 direction indicators (Price vs MA, RSI, Volume, Relative Strength) → ActionCategory (強力買入 🟢🟢 / 買入 🟢 / 持有 ✓ / 觀望 👀 / 減倉 ⚠️ / 出場 🔴🔴)
- **Layer D1b (Timing)**: 2 timing indicators (MACD, BB) → TimingModifier (✓ 時機好 / none / ⏳ 等回調) — modifies Entry recommendation emphasis only, does NOT change Action
- Timing modifier only shows for buy-side actions (強力買入, 買入, 持有). Suppressed for 觀望/減倉/出場.
- All-NEUTRAL (data_sufficient=False for all 4 direction) → 觀望 + "⚪ 資料不足以判斷"
- Implemented as pure-function decision tables, NOT if/elif chains. See `docs/STAFF_REVIEW_DECISIONS.md` I1 for full spec.
- Equal weight v1. Adjust based on accumulated history data.

## UX Output Rules (IMPORTANT)
- **NO template-based prose narrator**. Do not build Python/TS code that stitches indicator results into sentences.
- User-facing "plain language" = **scannable Pros/Cons UI list** (🟢/🔴 bullets), NOT paragraphs.
- Each indicator result surfaces as a structured item: `{category, tone, short_label, detail_on_expand}`.
- If rich narrative becomes necessary post-v1, use an LLM API (Claude Haiku 4.5 or Gemini Flash) with JSON input and a strict prompt. Never a hand-coded template.
- Rationale: template narrators devolve into nested if/else, sound robotic, have high maintenance cost, and scannable lists are better UX for decision-support.

## Hard Operational Invariants (DO NOT VIOLATE)
- **Indicators are pure functions**: `DataFrame -> IndicatorResult`. They NEVER call external APIs. All data fetching is centralized in `backend/app/ingestion/`.
- **Indicator series endpoints** (`GET /api/v1/ticker/{sym}/indicator/{name}/series` and `/api/v1/market/indicator/{name}/series`) use the canonical `NAME` constants from `app/indicators/` as URL slugs. Backend slug ↔ frontend slug must match exactly — don't introduce friendly aliases (`bollinger_bands`/`fed_funds`/`dxy_trend` are wrong; the correct slugs are `bollinger`, `fed_rate`, `dxy`).
- **summary_zh strings are GENERATED in Python**, not LLM-produced and not templated prose. Each series builder emits a one-line plain-Chinese judgment from rule-based logic (zone label + delta). Same rule as the existing UX Output Rule — scannable judgment, no narrator.
- **Broker CSV import is generic**: a single `BrokerCsvImporter` instance per `broker_key` lives in `app/ingestion/importers/__init__.py::IMPORTERS`. The broker_key flows through as `Trade.source` AND as the prefix in the deterministic `external_id` SHA-256, so trades from different brokers cannot collide on dedup even with identical (date, qty, price) tuples. Adding a broker = appending a tuple to `SUPPORTED_BROKERS` (no new code).
- **Watchlist onboardings queue; revalidations are exclusive**: `SymbolOnboardingService.start()` only rejects when an active `revalidation` BackfillJob exists. Concurrent onboardings spawn separate threads that serialize at `snapshot_write_mutex`. Revalidation start (`BackfillService`) keeps the broader "any active job" rejection.
- **One yfinance bulk call per daily_update**: `yf.download(" ".join(all_symbols), threads=False, ...)`. Never loop per-ticker.
- **SQLite WAL mode** via event listener (NOT connect_args `pragma`).
- **uvicorn --workers 1** hardcoded in docker-compose. APScheduler protected with fcntl.flock as belt-and-suspenders.
- **All API routes under `/api/v1/`** from day 1.
- **No plaintext secrets on disk**: SOPS + age encrypts all env vars. Age key in `/etc/eiswein/age.key` (chmod 600).
- **No raw SQL strings**: SQLAlchemy ORM or parameterized queries only.
- **httpOnly + SameSite=Lax cookies** for JWT. Never localStorage.
- **Schwab refresh tokens** AES-256-GCM encrypted at column level in BrokerCredential table.
- **Rate limit keyed by `CF-Connecting-IP`** with CF IP range validation middleware.
- **Every data fetch has timeout + retry + cache**: yfinance bulk with tenacity backoff, parquet cache before parsing.
- **Market calendar check** in daily_update: skip weekends/holidays. UI shows "最近交易日" not "today".
- **Dedup guards**: UNIQUE constraints + asyncio.Lock per-symbol for cold-start; stop_loss_triggered_at for intra-day alerts.

## Operational Scripts (in `scripts/`)
- `setup_secrets.sh` — first-time SOPS + age setup
- `set_password.py` — generate bcrypt hash for initial ADMIN_PASSWORD_HASH
- `reset_password_offline.py` — reset admin password without app running (SSH to VM)
- `rotate_age_key.sh` — rotate SOPS age encryption key
- `rotate_secrets.py` — rotate JWT_SECRET / ENCRYPTION_KEY (re-encrypts BrokerCredential)

## References (committed to repo)
- Implementation plan: `docs/IMPLEMENTATION_PLAN.md`
- Design decisions: `docs/DESIGN_DECISIONS.md`
- **Staff engineer review (40+ locked technical details)**: `docs/STAFF_REVIEW_DECISIONS.md` ← authoritative for any detail not explicit in IMPLEMENTATION_PLAN.md
- Sherry system context: `docs/SHERRY_SYSTEM.md`
