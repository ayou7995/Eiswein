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
├── api/          # FastAPI routes (one file per resource)
├── db/           # SQLAlchemy models + session
├── datasources/  # Abstract DataSource + yfinance/FRED/Schwab/Polygon impls
├── indicators/   # 12 indicator modules (each implements base.py)
├── signals/      # Voting, entry price, stop-loss, pros_cons (structured — NO template narrator)
├── security/     # Auth, encryption, rate limit, middleware
├── jobs/         # Cron: daily_update, backup, token_reminder
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
- App-level JWT (httpOnly cookie, SameSite=Strict) — second auth layer
- ALL API keys in env vars. NEVER in code or git.
- Schwab refresh tokens: AES-256 encrypted in SQLite
- Rate limiting (slowapi), CSP headers, HSTS, parameterized SQL only
- bcrypt (12 rounds) for password hashing
- Login throttling: 5 fails → 15 min lock, all attempts audited

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

## Signal Rules
- **Layer 1 (Market Posture)**: 4 market-regime indicators vote → 進攻/正常/防守
- **Layer 2 (Per-Ticker Action)**: 6 indicators → 強力買入🟢🟢 / 買入等回調🟢⏳ / 持有✓ / 觀望👀 / 減倉⚠️ / 出場🔴🔴
- Equal weight v1. Adjust based on accumulated history data.

## UX Output Rules (IMPORTANT)
- **NO template-based prose narrator**. Do not build Python/TS code that stitches indicator results into sentences.
- User-facing "plain language" = **scannable Pros/Cons UI list** (🟢/🔴 bullets), NOT paragraphs.
- Each indicator result surfaces as a structured item: `{category, tone, short_label, detail_on_expand}`.
- If rich narrative becomes necessary post-v1, use an LLM API (Claude Haiku 4.5 or Gemini Flash) with JSON input and a strict prompt. Never a hand-coded template.
- Rationale: template narrators devolve into nested if/else, sound robotic, have high maintenance cost, and scannable lists are better UX for decision-support.

## References (committed to repo)
- Implementation plan: `docs/IMPLEMENTATION_PLAN.md`
- Design decisions: `docs/DESIGN_DECISIONS.md`
- **Staff engineer review (40+ locked technical details)**: `docs/STAFF_REVIEW_DECISIONS.md` ← authoritative for any detail not explicit in IMPLEMENTATION_PLAN.md
- Sherry system context: `docs/SHERRY_SYSTEM.md`
