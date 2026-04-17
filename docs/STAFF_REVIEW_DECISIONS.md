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

### D1. Direction vs Timing separated — two independent decision layers (REVISED 2026-04-17)

Direction and timing indicators answer **different questions** and must NOT be mixed in one vote.

**Layer D1a — Direction (4 indicators) determines Action category:**

| Direction 🟢 | Direction 🔴 | Action |
|---|---|---|
| 4 | 0 | 強力買入 🟢🟢 |
| 3 | 0-1 | 買入 🟢 |
| 2 | 0-1 | 持有 ✓ |
| 1-2 | 1-2 | 觀望 👀 |
| 0-1 | 2-3 | 減倉 ⚠️ |
| 0 | 4 | 出場 🔴🔴 |

Direction indicators: Price vs MA, RSI (weekly), Volume anomaly, Relative strength vs SPX.

**Layer D1b — Timing (2 indicators) modifies Entry recommendation only:**

| Timing state | Badge | Entry tier emphasis |
|---|---|---|
| Both 🟢 (MACD + BB both favorable) | ✓ 時機好 | 積極進場 highlighted |
| Mixed | (no badge) | All three tiers equal emphasis |
| Both 🔴 (MACD + BB both unfavorable) | ⏳ 等回調 | 理想/保守 highlighted, 積極 dimmed |

Timing indicators: MACD, Bollinger Bands.

**Final UI composition:**
- Action badge (from D1a) always shown
- Timing modifier (from D1b) appended as small badge if non-mixed
- Examples:
  - `強力買入 🟢🟢 ✓ 時機好` — direction all green + timing favorable → full green light
  - `強力買入 🟢🟢 ⏳ 等回調` — direction all green but timing unfavorable (追高) → wait for pullback, already-held positions safe
  - `持有 ✓` — nothing special, just hold
  - `減倉 ⚠️` — direction weakening; timing indicators NOT shown (not relevant when exiting)
  - `出場 🔴🔴` — direction crashed; timing ignored

**Rules:**
- Timing modifier ONLY appears for buy-side actions (強力買入, 買入, 持有). For 觀望/減倉/出場, timing is not relevant — show direction-only badge.
- All-NEUTRAL (all 4 direction indicators `data_sufficient=False`): action = 觀望 👀 + note "⚪ 資料不足以判斷"

Implemented as pure-function decision tables in `signals/pros_cons.py`:
```python
def classify_direction(direction_results: list[IndicatorResult]) -> ActionCategory: ...
def classify_timing(timing_results: list[IndicatorResult]) -> TimingModifier: ...
def compose_signal(action, timing) -> Signal: ...
```
NOT if/elif chains.

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

## I. Final Review Round (2026-04-17)

### I1. Stock splits / dividends — yfinance auto_adjust=True, user responsible for manual actions
- yfinance `auto_adjust=True` silently adjusts historical close. DailyPrice.close is always adjusted.
- Position.avg_cost is user-input (manual). User must manually adjust their recorded avg_cost when corporate actions occur.
- UI warning on Position page: "Corporate actions (splits, dividends) are NOT automatically adjusted. Recheck your avg_cost after any split."
- v2: automated dividend-aware P&L calculator.

### I2. Age key loss — accept risk, document rotation + recovery procedures
- Primary: `/etc/eiswein/age.key` on VM (chmod 600, root).
- Backup: stored in user's 1Password.
- Loss scenario: age key + 1Password both lost = re-run Schwab OAuth (5 minutes), regenerate JWT/encryption secrets (5 minutes). Acceptable blast radius for a personal tool.
- `scripts/rotate_age_key.sh` — quarterly rotation procedure documented.
- NOT adding multi-recipient encryption (overkill for single-user with manageable recovery cost).

### I3. Forgotten password — offline reset script on VM
- `scripts/reset_password_offline.py` runs directly against SQLite (no app needed).
- Requires SSH access to VM (SSH key = identity proof).
- Interactive: prompts for new password, validates via zxcvbn, writes bcrypt hash to `users.password_hash`.
- Documented in `docs/OPERATIONS.md` runbook.

### I4. Cold-start duplicate request protection
- `Watchlist` UNIQUE(user_id, symbol) — second POST returns 409 Conflict.
- Background backfill task guards: checks `data_status != "pending"` before starting.
- Additionally: per-symbol `asyncio.Lock` in a process-level dict prevents concurrent backfill of same ticker.
- After backfill: `data_status` transitions pending → ready (success) or pending → failed (error, logged).

### I5. Email quota — Gmail with batch-summary fallback
- Daily quota tracker in `email_outbox` service: counter resets at midnight ET.
- Normal mode: 1 email per event (stop-loss hit, token expiry, etc.)
- When quota threshold 80% reached (400/500 daily): switch to "batch summary mode" for remainder of day — combine events into single summary email every hour
- In-app banner on dashboard when batch mode active
- Log WARN when quota exceeded
- v2: evaluate SendGrid free tier (100/day dedicated) if Gmail continues to be constraint

### I6. Weekend / holiday handling
- `jobs/daily_update.py` checks `pandas_market_calendars.get_calendar("NYSE")` on entry
- If market not open today → log "market closed, skipping" and return immediately
- UI header always displays "最近交易日: YYYY-MM-DD (Day)" — never uses "today" label unless market is open
- Intra-day stop-loss job only runs on trading days, between 9:30-16:00 ET (also via market calendar)

### I7. Centralized data pipeline — single fetch shared across indicators
- `backend/app/ingestion/daily_ingestion.py`: orchestrator that coordinates all data fetches
- Flow per daily_update:
  1. Fetch ALL ticker OHLCV in ONE yfinance bulk call: `yf.download(" ".join(all_symbols), ...)`
  2. Fetch macro data (DXY, 10Y, 2Y, Fed Funds Rate) from FRED in batched calls
  3. Persist raw data to DB (DailyPrice, MacroIndicator)
  4. For each ticker: compute all 12 indicators from DB (no network calls in indicator code)
  5. Store DailySignal + MarketSnapshot
- Indicator modules are pure functions: `DataFrame -> IndicatorResult`. They NEVER call data sources.
- Prevents API rate limit blowout (12 indicators × 50 tickers = 600 calls becomes 1 call + 4 FRED calls)

### I8. Dependency management — pip-tools + package-lock
- Backend: `requirements.in` (top-level deps) → `pip-compile` → `requirements.txt` (fully pinned including transitive)
- `make deps-update` regenerates requirements.txt and runs `pip audit`
- Frontend: `package-lock.json` committed (npm default). `npm audit` in CI.
- Docker: base image pinned by digest (`python:3.12-slim-bookworm@sha256:...`)

### I9. Audit log integrity — append-only convention
- `AuditLog` table: no UPDATE or DELETE operations in code, convention only (SQLite cannot enforce).
- Daily backup captures audit_log as immutable record (backup files are read-only once written).
- v2: consider hash chain if multi-user. Not worth complexity for single-user v1.

### I10. yfinance ToS disclosure
- Settings page footer: "Data sourced from Yahoo Finance via yfinance library. See https://finance.yahoo.com/terms"
- README.md mentions yfinance ToS concern + v2 plan to migrate to Polygon.io

### I11. BrokerCredential uniqueness
- DB constraint: UNIQUE(user_id, broker)
- v1 supports one credential per broker per user
- v2: multi-account support deferred

### I12. Cloudflare → backend plain HTTP (v1 acceptable)
- End-user → CF edge: HTTPS (terminated at CF)
- CF → backend via Cloudflare Tunnel: encrypted within tunnel (cloudflared uses TLS internally)
- Backend serves plain HTTP on :8000 (bound to localhost inside container)
- v2 audit item: self-signed cert on backend + CF origin cert for additional defense-in-depth
- Documented in `docs/SECURITY.md`

### I13. Performance budgets (enforced as success criteria)
- Dashboard initial load: < 2s p95 on simulated 4G (Lighthouse)
- API endpoint response: < 200ms p95
- Daily update job: < 5 minutes total
- Instrumentation: simple timing logs via structlog `logger.info("duration_ms=...", ...)`
- Lighthouse run in CI on frontend PRs

### I14. Schwab OAuth UX — expiry handling
- Token refresh attempted automatically by app on each Schwab call if expired_at approaching
- If refresh fails or >7 days elapsed: token considered expired
- On expiry:
  - Settings page red banner: "⚠️ Schwab 連接已過期，請重新授權"
  - Daily email reminder if `<2 days` remaining
  - App falls back to yfinance silently for data (no user interruption)
  - User clicks "重新連接" → OAuth redirect flow → token refreshed
- Token state shown in Settings: 🟢 connected (N days left) | 🟡 <2 days | 🔴 expired

### I15. SQLite VACUUM — weekly maintenance
- `jobs/vacuum.py`: runs weekly (Sunday 3:00 AM ET, low traffic)
- `PRAGMA auto_vacuum=INCREMENTAL` set on DB creation
- `PRAGMA incremental_vacuum` in weekly job (non-blocking partial VACUUM)
- Occasionally full VACUUM during maintenance windows if fragmentation high

### I16. Parquet cache eviction
- Retention: 7 days
- Daily backup job appends: `find data/cache/yfinance -mtime +7 -delete`
- Cache files named `{YYYY-MM-DD}_{symbols_sha1}.parquet`

### I17. Ticker input validation
- Pydantic validator: `@field_validator('symbol') def normalize(cls, v): return v.strip().upper()`
- Regex: `^[A-Z0-9.\-]{1,10}$` (allows BRK.B, class-A style tickers)
- Frontend: HTML input `pattern` attribute + real-time feedback
- Reject lowercase, whitespace, special chars (except `.` and `-`) with 422 + specific error code

### I18. Delisted / invalid ticker UX
- yfinance returns empty DataFrame or raises
- DataSource catches → returns `DataSourceError` with `reason="delisted_or_invalid"`
- Update `Ticker.is_active = False` + `Watchlist.data_status = "delisted"`
- UI: grey out row, show "🚫 Delisted / Invalid" badge, disable action button
- User can remove from watchlist but history is preserved

### I19. All-NEUTRAL per-ticker signal
- If all 4 direction indicators have `data_sufficient=False`: action = 觀望 👀
- UI shows "⚪ 資料不足以判斷" message
- Typically happens for recent IPOs (<200 days history)

### I20. Color blindness — text + shape redundancy
- SignalBadge component renders: emoji + Chinese text label + visible letter indicator
- Example: `🟢 買` instead of just `🟢`
- ARIA label: `aria-label="強力買入，評分 Green"`
- CSS `@media (prefers-contrast: more)` adds border/icon patterns
- Test with Chrome DevTools vision deficiency simulator

### I21. Secret rotation cadence
- JWT_SECRET: rotate yearly. Rotation invalidates all sessions (user re-logins).
- ENCRYPTION_KEY: rotate yearly. Rotation requires re-encrypting all BrokerCredential rows (script provided).
- Admin password: user's choice, recommend quarterly.
- `scripts/rotate_secrets.py` handles all three.
- Documented in `docs/OPERATIONS.md`.

### I22. NTP / time sync
- Dockerfile: `apt-get install -y ntpdate`
- docker-entrypoint.sh: `ntpdate -s time.google.com || true` on startup
- Verify container timezone set to UTC via `ENV TZ=UTC`
- App code always uses `America/New_York` for market dates (via zoneinfo)

### I23. Healthcheck endpoint
- `GET /api/v1/health` returns:
  ```json
  {
    "status": "ok",
    "db": {"status": "ok", "last_backup": "2026-04-17T07:00:00Z"},
    "scheduler": {"status": "ok", "last_daily_update": "2026-04-17T06:30:00-04:00"},
    "data_sources": {"yfinance": "ok", "fred": "ok", "schwab": "not_configured"}
  }
  ```
- Dockerfile HEALTHCHECK: `CMD curl -f http://localhost:8000/api/v1/health || exit 1`
- No auth required (internal check) but only returns minimal info + obeys rate limit

### I24. Graceful shutdown
- uvicorn: `--timeout-graceful-shutdown 30` (30s to complete in-flight requests)
- FastAPI lifespan: on shutdown, call `scheduler.shutdown(wait=True)` + close DB engine
- Signal handling: SIGTERM handled by uvicorn; Docker stops container with SIGTERM then SIGKILL after 30s grace
- APScheduler jobs mid-run: allowed to complete up to grace period; longer jobs logged as interrupted

### I25. Migration failure handling
- docker-entrypoint.sh: `alembic upgrade head` runs before uvicorn
- If migration fails: entrypoint `exit 1` → container exits → docker restart policy retries
- NEVER silently start with broken/outdated schema
- Alembic migrations must be idempotent (use `op.create_table(... if not exists)` patterns where needed)

### I26. CI/test infrastructure
- `.github/workflows/test.yml`:
  - Backend: pytest with `--cov=backend --cov-report=xml`
  - Frontend: `vitest run --coverage`
  - Coverage reporting (Codecov or artifact upload), NOT enforced threshold in v1
  - Dependency audit: `pip audit` + `npm audit` (fail on high/critical)
  - Linting: ruff (backend), eslint (frontend)
- `Makefile` with common targets: `test`, `lint`, `deps-update`, `migrate`, `dev`
- E2E tests (Playwright) deferred to v2

## J. Items Deferred to v2 (explicitly documented)

- PWA offline mode (scaffold present, disabled)
- URL shareability / share tokens
- Pre-market / after-hours data
- Multi-brokerage support
- Automated dividend-aware P&L
- SBOM generation (cyclonedx)
- E2E Playwright tests
- Self-signed TLS on backend
- Multi-recipient SOPS encryption
- Dependabot / Renovate auto-updates (manual for v1)
- LLM-based narrative generator (Claude Haiku / Gemini Flash)
