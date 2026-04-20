# Eiswein

Personal stock market decision-support tool. Analyzes a user-managed watchlist using 12 technical indicators and produces daily signal reports with entry/exit/stop-loss recommendations.

Inspired by Heaton's Sherry trading system. Positioning: systematic decision-support / quantamental advisory. **Not** automated quant trading — human makes all trading decisions.

## Status

Phase 3 complete (signal composition layer: D1a Direction +
D1b Timing decision tables, market-posture classifier, 3-tier entry
prices, dynamic stop-loss, Pros/Cons structured list, TickerSnapshot /
MarketSnapshot / MarketPostureStreak persistence, two new read
endpoints). Phase 4 (dashboard UI) is next. See
`docs/IMPLEMENTATION_PLAN.md` for the full phased plan and
`docs/STAFF_REVIEW_DECISIONS.md` for locked technical decisions.

### Phase 3 API surface (additive to Phase 1-2)

- `GET    /api/v1/market-posture`                    — latest MarketSnapshot + streak badge + 4 regime indicators rendered as Pros/Cons items
- `GET    /api/v1/ticker/{symbol}/signal`            — composed Action (D1a) + TimingModifier (D1b) + 3-tier entry prices + stop-loss + Pros/Cons list
- `POST   /api/v1/data/refresh`                      — now also composes + persists `TickerSnapshot`/`MarketSnapshot` after indicator compute

### Signal composition rules (D1, revised 2026-04-17)

- **D1a (Direction)**: 4 direction indicators vote → one of `強力買入 🟢🟢 / 買入 🟢 / 持有 ✓ / 觀望 👀 / 減倉 ⚠️ / 出場 🔴🔴` via a pure-function decision table (no if/elif chains).
- **D1b (Timing)**: 2 timing indicators (MACD, BB) → modifier `✓ 時機好 / (mixed, no badge) / ⏳ 等回調`. Only surfaces on buy-side actions (強力買入/買入/持有); suppressed for 觀望/減倉/出場.
- **Layer 1 (Market Posture)**: 4 regime indicators → `進攻 / 正常 / 防守`. Surfaced as a *context badge* (D2) — never silently downgrades per-ticker actions.
- **Streaks**: consecutive-day streak tracked only for market posture, not per-indicator (D3).
- **Pros/Cons output**: indicator results are surfaced as a scannable list of `{category, tone, short_label, detail}` bullets. **No prose / template narrator** (per CLAUDE.md UX rule) — frontend renders the list; any future rich-narrative generation would go through an LLM API with a strict JSON prompt.

### Phase 2 API surface (additive to Phase 1)

- `GET    /api/v1/ticker/{symbol}/indicators`        — most recent 8 per-ticker computed indicator results (404 if no rows yet)
- `POST   /api/v1/data/refresh`                      — now also computes + persists `DailySignal` rows after price/macro UPSERT

### Phase 1 API surface

- `GET    /api/v1/watchlist`                         — list user's watchlist
- `POST   /api/v1/watchlist`                         — add ticker (cold-start backfill within 5s budget; 202 + pending on timeout)
- `DELETE /api/v1/watchlist/{symbol}`                — remove from watchlist (price history preserved)
- `GET    /api/v1/data/status`                       — data-source health + per-user ticker status summary
- `GET    /api/v1/ticker/{symbol}?only_status=1`     — lightweight status poll for frontend during pending backfill

### Indicator engine notes

- **Pure functions**: every module in `backend/app/indicators/` consumes a pandas DataFrame + an `IndicatorContext` and returns a frozen `IndicatorResult`. No network I/O.
- **DXY proxy**: FRED does not republish raw DXY — we use `DTWEXBGS` (Trade-Weighted USD Broad Index) and document the substitution.
- **Wilder's RSI, MACD, Bollinger** are hand-rolled in `indicators/_helpers.py` on top of pandas EWM / rolling. We avoid `pandas_ta` because its latest release imports `numpy.NaN` (removed in numpy 2.x) and is abandoned.
- **Test fixtures**: `scripts/generate_indicator_fixtures.py` regenerates real-market parquet snapshots under `backend/tests/fixtures/` (run manually when formulas change; tests themselves are hermetic).

### Phase 1 environment

- `FRED_API_KEY` — optional. Required only for macro (10Y/2Y/DXY/VIX/Fed Funds) ingestion. `run_daily_update` logs and continues when absent, so single-ticker cold-start backfill works without it.
- `DATA_SOURCE_PROVIDER` — default `yfinance`; `schwab` / `polygon` stubs raise `NotImplementedError` until v2.
- `CACHE_DIR` — default `./data/cache`; parquet cache for yfinance responses (7-day retention).
- `WATCHLIST_MAX_SIZE` — default 100 per B3.

## Stack

- **Backend**: FastAPI (Python 3.12) + SQLite + SQLAlchemy
- **Frontend**: React + TypeScript + Tailwind CSS + TradingView Lightweight Charts
- **Deployment**: Single Docker container on Oracle Cloud Free Tier / Hetzner
- **Network**: Cloudflare Tunnel + Cloudflare Access (OAuth)

## Setup (WIP)

```bash
# Copy env template
cp .env.example .env
# Generate secrets and update .env:
python -c "import secrets; print(secrets.token_urlsafe(64))"                        # JWT_SECRET
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"  # ENCRYPTION_KEY
python scripts/set_password.py                                                      # ADMIN_PASSWORD_HASH

# Backend
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Apply migrations
alembic upgrade head

# Run
uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000

# Tests, lint, type (from repo root)
make test
make lint
make type

# Frontend (Phase 1+)
cd ../frontend
cp .env.example .env
npm install
npm run dev
```

### Frontend scripts

```bash
cd frontend
npm run dev         # Vite dev server on :5173 (proxies /api to VITE_API_URL)
npm run typecheck   # tsc --noEmit (strict mode)
npm run lint        # eslint (zero warnings allowed)
npm test            # vitest run
npm run build       # type-check + production build into dist/
```

### Frontend stack (Phase 0)

- React 18 + TypeScript strict mode + Vite 5
- Tailwind CSS 3 (dark mode via `class`, signal colors extended)
- TanStack Query 5 (server state), react-router-dom v6, react-hook-form + Zod (forms)
- react-error-boundary (page + app fallbacks)
- lightweight-charts (installed for Phase 4, not yet rendered)
- vitest + @testing-library/react + jsdom (tests)

### Frontend security invariants

- JWT is carried **only** in httpOnly Set-Cookie — never localStorage, never body
- fetch wrapper sends `credentials: 'include'` and coalesces concurrent 401s onto a single refresh call
- Every API boundary parsed with a Zod schema; failures surface as `SchemaValidationError`
- No `dangerouslySetInnerHTML` anywhere

## Architecture

```
backend/app/
├── api/          # FastAPI routes
├── db/           # SQLAlchemy models
├── datasources/  # Data source interface + implementations
├── indicators/   # 12 indicator modules
├── signals/      # Voting, entry/stop-loss, narrator
├── security/     # Auth, encryption, rate limit
├── jobs/         # Cron jobs
└── utils/        # Shared utilities

frontend/src/
├── pages/        # Route components
├── components/   # Reusable UI
├── api/          # Typed fetch wrappers + Zod schemas
├── hooks/        # Shared hooks
└── lib/          # Utilities, constants
```

## Development Conventions

See `CLAUDE.md` for the full Definition of Done and coding standards.

Code is developed using Claude Code's multi-agent orchestration:
- `backend-builder` — Backend implementation
- `frontend-builder` — Frontend implementation
- `security-auditor` — Security reviews (run after every phase)
- `test-writer` — Test coverage

## Security

Security is the #1 priority. See `CLAUDE.md` for the full security model. Highlights:
- Dual-layer auth: Cloudflare Access (OAuth) + app JWT (httpOnly cookies)
- No public ports on VM (Cloudflare Tunnel only)
- AES-256 encryption for stored broker tokens
- Rate limiting, CSP, HSTS, parameterized SQL only
- All secrets via environment variables

## License

Private / personal use.
