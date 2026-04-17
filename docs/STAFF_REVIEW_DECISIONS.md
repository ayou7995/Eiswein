---
name: Eiswein Staff Engineer Review — Locked Decisions
description: All 40+ detailed technical decisions from the staff engineer review (2026-04-16). These are finalized design choices that must not be relitigated during implementation.
type: project
originSessionId: 53ac829a-06b7-4aff-a0a6-74e2823ce65d
---
# Staff Engineer Review — Locked Decisions (2026-04-16)

After the design was grilled section by section, the user made explicit decisions on each. This document captures them for reference during implementation.

## A. Data Model

### A1. Ticker is the master, Watchlist + Position are consumers
- Independent `Ticker` table
- `DailyPrice` FK → `Ticker` (not Watchlist)
- Removing from watchlist does NOT delete price history
- Position's ticker auto-included in indicator computation (even if not in watchlist)

### A2. UPSERT with versioning for computed data
- `DailySignal` UNIQUE(symbol, date), `INSERT ... ON CONFLICT DO UPDATE`
- NEVER use SQLite `INSERT OR REPLACE` (cascades FKs)
- Add `computed_at: datetime` — when was this calculated
- Add `indicator_version: str` (semver, e.g., "1.0.0") — preserves historical judgment across formula changes

### A3. Keep User table from day 1
- Design for future multi-user; v1 is single admin user
- Schema: id, username, email (nullable), password_hash (bcrypt 12), is_active, is_admin, timestamps, last_login_at/ip, failed_login_count, locked_until
- All user-owned tables (Watchlist, Position, Trade, BrokerCredential) have user_id FK
- First startup: seed admin from ADMIN_USERNAME + ADMIN_PASSWORD_HASH env; refuse to start if missing

### A4. Trade as append-only source of truth, Position as derived
- `Position` row never deleted, only updated
- `Trade` is append-only event log (buy/sell transactions)
- Position.shares conceptually derived from sum of trades
- "I once held X" history naturally preserved

### A5. Alembic for schema migration
- Introduce in Phase 0 (not bolted on later)
- First migration: empty → initial schema
- `docker-entrypoint.sh` runs `alembic upgrade head` on startup (idempotent)

## B. API Contract

### B1. Login response via httpOnly cookie + structured error
- JWT in Set-Cookie (httpOnly, SameSite=Lax, Secure)
- Never in response body
- 401 with `{"error": {"code": "invalid_password", "attempts_remaining": N}}`
- 403 with `{"error": {"code": "locked_out", "retry_after_seconds": N}}`

### B2. Token refresh with request deduplication
- TanStack Query: first 401 triggers refresh; all in-flight 401s wait on same promise
- Prevents thundering herd of refresh calls

### B3. Watchlist hard cap 100 tickers
- Configurable, default 100
- 422 error on overflow
- Rationale: yfinance bulk download breaks down beyond ~100

### B4. Pagination with consistent wrapper
- `?start_date=&end_date=&limit=N` query params
- Default limit=30 for history endpoints
- Always wrap list responses: `{data: [...], total: N, has_more: bool}`

### B5. API versioning from day 1
- All routes under `/api/v1/*`
- Breaking changes → `/api/v2/*` with v1 kept during migration period

### B6. Standardized error envelope
```json
{
  "error": {
    "code": "invalid_password",        // stable string for frontend logic
    "message": "密碼錯誤",              // user-facing Chinese
    "details": {"attempts_remaining": 3} // optional structured data
  }
}
```
- All custom exceptions subclass `EisweinError` and serialize to this shape
- FastAPI global exception handler converts

## C. Indicator Correctness

### C1. Exchange date + explicit timezone
- Store dates as exchange-local (America/New_York for US equities)
- API response: `{"date": "2026-04-16", "timezone": "America/New_York"}`
- Frontend: `Intl.DateTimeFormat` for user-local display, always label "(ET)"

### C2. RSI via pandas_ta with Wilder's smoothing
- Use `pandas_ta` library
- Explicit Wilder's smoothing option
- Validate ±0.5 against TradingView screenshots

### C3. A/D Day strict O'Neil definition
- `volume > prev_volume` AND up → Accumulation
- `volume > prev_volume` AND down → Distribution
- Volume flat/down → Neutral (not counted)

### C4. Volume anomaly: 20-day SMA, excluding today
- Prior 20 days average
- Spike = `today_volume > 2 * avg`

### C5. Relative strength: 20-day rolling cumulative return
- `(price_today / price_20_days_ago) - 1` for ticker and SPX
- Compare the difference

### C6. Bollinger Bands: standard 2σ, 20-period
### C7. MACD: standard (12, 26, 9)

### C8. Yield spread visual tiers
- `>0.2%` 🟢 healthy
- `0 to 0.2%` 🟡 flattening
- `≤0` 🔴 inverted

### C9. DXY direction: 20-day SMA slope, 5-day streak
- 5 consecutive days of 20MA rising = 🔴 (strong, tech-negative)
- Flat = 🟡
- 5 consecutive days of 20MA falling = 🟢 (weak, tech-positive)

### C10. Insufficient data handling
- `IndicatorResult` has `data_sufficient: bool`
- When false: signal=NEUTRAL, short_label="資料不足"
- UI shows "N/A", does NOT count toward voting

## D. Signal Rules

### D1. Explicit decision table for 6 action categories
Per-ticker voting on 6 indicators (4 direction + 2 timing):

| 🟢 count | 🔴 count | Action |
|---|---|---|
| ≥5 | ≤1 | 強力買入 🟢🟢 |
| 3-4 | 0-1 | 買入等回調 🟢⏳ (check timing) |
| 2-3 | 1-2 | 持有 ✓ |
| 1-2 | 2-3 | 觀望 👀 |
| ≤1 | 3-4 | 減倉 ⚠️ |
| ≤1 | ≥5 | 出場 🔴🔴 |

Implemented as `pros_cons.py` decision table, NOT if/elif chain.

### D2. Market regime as context badge, not auto-downgrade
- Per-ticker action NOT silently downgraded when market is 🔴
- UI shows "⚠ 大盤逆風" badge next to action
- Narrative text: "個股訊號強，但大盤防守，建議減少進場規模"
- User sees raw signals + context

### D3. Streaks — only market posture, not per-indicator
- `MarketPostureStreak` table tracks consecutive days of same posture
- UI shows "進攻 3 天 ✨" on dashboard
- Do NOT compute streaks on 12 individual indicators (too much noise)

### D4. Intra-day stop-loss alerts
- NEW v1 requirement: separate job runs every 30 minutes during US market hours
- Checks all Positions against stop-loss prices
- Triggers immediate email alert + in-app red banner
- Action auto-escalates to "出場" with `stop_loss_triggered: true`

## E. Security Hardening

### E1. Password policy
- `.env.example` documents "min 16 chars or passphrase"
- `scripts/set_password.py` checks length + uses `zxcvbn` to reject weak passwords

### E2. JWT rotation on every login
- POST /api/login issues fresh JWT
- Old token naturally invalidates (short expiry, stateless)

### E3. Rate limit keyed by real client IP
- Use `CF-Connecting-IP` header (set by Cloudflare)
- Middleware validates request source is Cloudflare IP range (prevents header spoofing)

### E4. SameSite=Lax (not Strict)
- Rationale: Strict breaks email-link UX (user hostility)
- Lax still protects POST/PUT/DELETE (the dangerous ones)

### E5. Lock IP, not account
- IP-based lockout (5 fails → 15 min)
- Global threshold alarm: >20 fails/min across all IPs → email alert
- No account lockout (prevents DoS against legitimate user)

### E6. Log sanitization
- `sanitize_log_payload(d)` helper: recursive redaction of keys matching `/password|token|secret|key/i`
- structlog processor chain MUST include this
- Test: log dict with password, assert stdout has `[REDACTED]`, not real value

### E7. Strict CSP
```
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';   // Tailwind requires
  img-src 'self' data:;
  connect-src 'self';
  font-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';
```

## F. Frontend Architecture

### F1. React Router v6
### F2. State management stack
- **Server state**: TanStack Query
- **Auth state**: React Context (backend-authoritative via cookie)
- **Form state**: react-hook-form + Zod
- No Redux/Zustand

### F3. Mobile chart optimization
- Default on mobile: K-line + 200MA only
- "Show advanced" toggle: adds Bollinger + 50MA + volume
- Chart `aspect-ratio: 16/10`, width 100%

### F4. PWA scaffolding ready, disabled in v1
- `vite-plugin-pwa` installed and configured
- Commented out / disabled
- 5-minute activation when wanted

### F5. Error boundary strategy
- `react-error-boundary` for render errors at page level
- `window.addEventListener('unhandledrejection')` for async
- TanStack Query `onError` for hook-level errors
- All errors reported to `/api/audit/client-error` endpoint

## G. Deployment / Infra

### G1. Cloudflare Named Tunnel (not Legacy)
### G2. Docker image target <300MB
- Multi-stage build
- `--no-cache-dir` for pip
- `.dockerignore` excludes tests, node_modules, parquet cache, venv

### G3. GitHub Actions CI/CD + Watchtower on VM
- Push to main → build → push to `ghcr.io/ayou7995/eiswein:latest`
- VM runs Watchtower to auto-pull
- No SSH needed for regular deploys

### G4. SOPS + age for secret management (NO PLAINTEXT)
- All secrets encrypted at rest in git (`secrets/eiswein.enc.yaml`)
- Age private key on VM at `/etc/eiswein/age.key` (chmod 600, root)
- Age key backed up to 1Password
- Docker entrypoint: `sops -d secrets/eiswein.enc.yaml | export ...`
- `/tmp` is tmpfs (RAM) — decrypted env never hits disk
- Schwab refresh tokens AES-256-GCM encrypted in DB (column-level)
- Boot volume encryption enabled on VM (Oracle Cloud / Hetzner)
- Log sanitizer ensures no secret leaks to logs
- Response schema whitelist prevents secret leaks in API

## H. Design Gaps Resolved

### H1. Schwab interface stubbed, yfinance for v1
- `DataSource` abstract class in Phase 1
- `YFinanceSource` + `FREDSource` fully implemented in Phase 1
- `SchwabSource` + `PolygonSource` stubs (raise NotImplementedError on data methods)
- BUT Schwab **OAuth flow + credential storage** IS in v1 (Settings page "Connect Schwab")
- User can manually re-auth when token expires
- v2 only needs to implement `SchwabSource.bulk_download()` to fully switch data source

### H2. Multi-device last-write-wins
- Accept race conditions (single user, low probability)
- UI banner: "Last updated N min ago from another device"
- TanStack Query `refetchOnWindowFocus: true` + 5-min stale time

### H3. Email outbox pattern
- `email_outbox` table: pending / sent / failed
- `retry_failed_emails` job every 1 hour
- >24h still failing → audit_log entry + in-app banner

### H4. Fixture-based indicator tests
- `tests/fixtures/ohlcv_sp500_2024.parquet` — real historical data snapshot
- Snapshot tests: record first-run, compare thereafter
- Manual snapshot update when formulas intentionally change
